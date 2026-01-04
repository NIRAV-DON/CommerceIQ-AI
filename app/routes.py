from flask import render_template, url_for, flash, redirect, request, Blueprint, session
from . import db, bcrypt
from .forms import RegistrationForm, LoginForm, ProductForm, ReviewForm
from .models import User, Product, Order, OrderItem, Review
from flask_login import login_user, current_user, logout_user, login_required
from functools import wraps
from .ai_engine import forecasting, recommendations

# Create a Blueprint object
main = Blueprint('main', __name__)

# Admin required decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('main.home'))
        return f(*args, **kwargs)
    return decorated_function

@main.route("/dashboard")
@login_required
def dashboard():
    total_products = Product.query.count()
    cart_count = len(session.get('cart', {}))

    return render_template(
        "dashboard.html",
        total_products=total_products,
        cart_count=cart_count
    )

@main.route("/")
@main.route("/home")
def home():
    query = request.args.get('query')
    if query:
        products = Product.query.filter(Product.name.contains(query)).all()
    else:
        products = Product.query.all()
    return render_template('home.html', products=products)

@main.route("/search", methods=['POST'])
def search():
    query = request.form.get('search_query')
    return redirect(url_for('main.home', query=query))

@main.route("/register", methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))
    form = RegistrationForm()
    if form.validate_on_submit():
        hashed_password = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
        user = User(username=form.username.data, email=form.email.data, password_hash=hashed_password)
        db.session.add(user)
        db.session.commit()
        flash('Your account has been created! You are now able to log in', 'success')
        return redirect(url_for('main.login'))
    return render_template('register.html', title='Register', form=form)

@main.route("/login", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('main.admin_dashboard'))
        return redirect(url_for('main.home'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()

        if user and bcrypt.check_password_hash(user.password_hash, form.password.data):
            login_user(user, remember=form.remember.data)

            # 🔑 ROLE BASED REDIRECT
            if user.role == 'admin':
                return redirect(url_for('main.admin_dashboard'))
            else:
                return redirect(url_for('main.home'))

        else:
            flash('Login Unsuccessful. Please check email and password', 'danger')

    return render_template('login.html', title='Login', form=form)




@main.route("/logout")
def logout():
    logout_user()
    return redirect(url_for('main.home'))

@main.route("/product/<int:product_id>", methods=['GET', 'POST'])
def product(product_id):
    product = Product.query.get_or_404(product_id)
    form = ReviewForm()
    if form.validate_on_submit():
        review = Review(rating=form.rating.data, comment=form.comment.data, author=current_user, product=product)
        db.session.add(review)
        db.session.commit()
        flash('Your review has been submitted!', 'success')
        return redirect(url_for('main.product', product_id=product.product_id))
    reviews = Review.query.filter_by(product_id=product.product_id).order_by(Review.created_at.desc()).all()
    return render_template('product_detail.html', title=product.name, product=product, form=form, reviews=reviews)

@main.route("/add_to_cart/<int:product_id>", methods=['POST'])
@login_required
def add_to_cart(product_id):
    quantity = int(request.form.get('quantity', 1))

    cart = session.get('cart', {})
    cart[str(product_id)] = cart.get(str(product_id), 0) + quantity
    session['cart'] = cart

    flash('Product added to cart!', 'success')
    return redirect(url_for('main.cart'))


@main.route("/cart")
@login_required
def cart():
    cart_session = session.get('cart', {})
    cart_items = []
    total_price = 0
    for product_id, quantity in cart_session.items():
        product = Product.query.get(product_id)
        if product:
            item_total = product.price * quantity
            total_price += item_total
            cart_items.append({'product': product, 'quantity': quantity, 'item_total': item_total})
    return render_template('cart.html', title='Shopping Cart', cart_items=cart_items, total_price=total_price)

@main.route("/remove_from_cart/<int:product_id>")
@login_required
def remove_from_cart(product_id):
    cart = session.get('cart', {})
    if str(product_id) in cart:
        del cart[str(product_id)]
        session['cart'] = cart
        flash('Product removed from cart.', 'success')
    return redirect(url_for('main.cart'))

@main.route("/checkout", methods=['GET', 'POST'])
@login_required
def checkout():
    # Checkout logic goes here
    # For now, let's just clear the cart and redirect
    cart = session.get('cart', {})
    if not cart:
        flash('Your cart is empty.', 'info')
        return redirect(url_for('main.home'))
    
    # Create order
    total_price = 0
    order_items = []
    for product_id, quantity in cart.items():
        product = Product.query.get(product_id)
        if product:
            total_price += product.price * quantity
            order_items.append(OrderItem(product_id=product_id, quantity=quantity, price_per_unit=product.price))
    
    # Assuming a static shipping address for simplicity
    order = Order(user_id=current_user.user_id, total_amount=total_price, shipping_address="123 Example St, City, Country", items=order_items)
    db.session.add(order)
    db.session.commit()

    session.pop('cart', None) # Clear the cart
    flash('Your order has been placed successfully!', 'success')
    return redirect(url_for('main.home'))


# --- ADMIN ROUTES ---
@main.route("/admin/dashboard")
@login_required
@admin_required
def admin_dashboard():
    forecast_data = forecasting.get_sales_forecast()
    frequent_pairs = recommendations.get_frequent_pairs()
    return render_template('admin_dashboard.html', title='Admin Dashboard', forecast_data=forecast_data, frequent_pairs=frequent_pairs)

@main.route("/admin/product/new", methods=['GET', 'POST'])
@login_required
@admin_required
def add_product():
    form = ProductForm()
    if form.validate_on_submit():
        product = Product(name=form.name.data, description=form.description.data, price=form.price.data, stock_quantity=form.stock_quantity.data, category=form.category.data, image_url=form.image_url.data)
        db.session.add(product)
        db.session.commit()
        flash('The product has been added!', 'success')
        return redirect(url_for('main.home'))
    return render_template('add_product.html', title='Add Product', form=form)

