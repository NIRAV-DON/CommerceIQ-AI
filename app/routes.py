from flask import render_template, url_for, flash, redirect, request, Blueprint, session
from . import db, bcrypt
from .forms import RegistrationForm, LoginForm, ProductForm, ReviewForm
from .models import User, Product, Order, OrderItem, Review
from flask_login import login_user, current_user, logout_user, login_required
from functools import wraps

# Blueprint
main = Blueprint('main', __name__)

# -------------------- ADMIN DECORATOR --------------------
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('main.home'))
        return f(*args, **kwargs)
    return decorated_function

# -------------------- HOME --------------------
@main.route("/")
@main.route("/home")
def home():
    category = request.args.get('category')
    query = request.args.get('query')

    products = Product.query

    if category:
        products = products.filter_by(category=category)

    if query:
        products = products.filter(Product.name.contains(query))

    products = products.all()

    return render_template(
        'home.html',
        products=products,
        selected_category=category
    )


# -------------------- SEARCH --------------------
@main.route("/search", methods=["POST"])
def search():
    query = request.form.get("search_query")
    return redirect(url_for("main.home", query=query))

# -------------------- REGISTER --------------------
@main.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))

    form = RegistrationForm()
    if form.validate_on_submit():
        hashed_password = bcrypt.generate_password_hash(
            form.password.data
        ).decode("utf-8")

        user = User(
            username=form.username.data,
            email=form.email.data,
            password_hash=hashed_password,
            role="customer"
        )
        db.session.add(user)
        db.session.commit()

        flash("Account created successfully!", "success")
        return redirect(url_for("main.login"))

    return render_template("register.html", form=form)

# -------------------- LOGIN --------------------
@main.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        if current_user.role == "admin":
            return redirect(url_for("main.admin_dashboard"))
        return redirect(url_for("main.home"))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()

        if user and bcrypt.check_password_hash(user.password_hash, form.password.data):
            login_user(user, remember=form.remember.data)

            if user.role == "admin":
                return redirect(url_for("main.admin_dashboard"))
            else:
                return redirect(url_for("main.home"))

        flash("Login failed. Check email or password.", "danger")

    return render_template("login.html", form=form)

# -------------------- LOGOUT --------------------
@main.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.home"))

# -------------------- CUSTOMER DASHBOARD --------------------
@main.route("/dashboard")
@login_required
def dashboard():
    cart_count = len(session.get("cart", {}))
    total_products = Product.query.count()
    return render_template(
        "dashboard.html",
        cart_count=cart_count,
        total_products=total_products
    )

# -------------------- PRODUCT DETAIL --------------------
@main.route("/product/<int:product_id>", methods=["GET", "POST"])
def product_detail(product_id):
    product = Product.query.get_or_404(product_id)
    form = ReviewForm()

    if form.validate_on_submit():
        review = Review(
            rating=form.rating.data,
            comment=form.comment.data,
            author=current_user,
            product=product
        )
        db.session.add(review)
        db.session.commit()
        flash("Review added!", "success")
        return redirect(url_for("main.product_detail", product_id=product_id))

    reviews = Review.query.filter_by(
        product_id=product_id
    ).order_by(Review.created_at.desc()).all()

    return render_template(
        "product_detail.html",
        product=product,
        form=form,
        reviews=reviews
    )

# -------------------- CART --------------------
@main.route("/add_to_cart/<int:product_id>", methods=["POST"])
@login_required
def add_to_cart(product_id):
    product = Product.query.get_or_404(product_id)

    quantity = int(request.form.get("quantity", 1))

    # ❌ STOCK CHECK
    if product.stock_quantity <= 0:
        flash("Product is out of stock!", "danger")
        return redirect(url_for("main.product_detail", product_id=product_id))

    if quantity > product.stock_quantity:
        flash(
            f"Only {product.stock_quantity} item(s) available in stock.",
            "danger"
        )
        return redirect(url_for("main.product_detail", product_id=product_id))

    cart = session.get("cart", {})
    cart[str(product_id)] = cart.get(str(product_id), 0) + quantity
    session["cart"] = cart

    flash("Product added to cart!", "success")
    return redirect(url_for("main.cart"))

@main.route("/orders")
@login_required
def orders():
    user_orders = Order.query.filter_by(
        user_id=current_user.user_id
    ).order_by(Order.order_date.desc()).all()

    return render_template(
        "orders.html",
        orders=user_orders
    )


@main.route("/cart")
@login_required
def cart():
    cart_session = session.get("cart", {})
    cart_items = []
    total_price = 0

    for pid, qty in cart_session.items():
        product = Product.query.get(int(pid))
        if product:
            item_total = product.price * qty
            total_price += item_total
            cart_items.append({
                "product": product,
                "quantity": qty,
                "item_total": item_total
            })

    return render_template(
        "cart.html",
        cart_items=cart_items,
        total_price=total_price
    )

@main.route("/remove_from_cart/<int:product_id>")
@login_required
def remove_from_cart(product_id):
    cart = session.get("cart", {})
    cart.pop(str(product_id), None)
    session["cart"] = cart
    flash("Product removed.", "info")
    return redirect(url_for("main.cart"))

# -------------------- CHECKOUT --------------------
@main.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    cart = session.get("cart", {})

    if not cart:
        flash("Your cart is empty.", "info")
        return redirect(url_for("main.home"))

    total_price = 0

    # ✅ CREATE ORDER FIRST
    order = Order(
        user_id=current_user.user_id,
        total_amount=0,
        shipping_address="123 Example St, City, Country"
    )
    db.session.add(order)
    db.session.commit()  # 🔴 IMPORTANT

    # ✅ PROCESS EACH PRODUCT
    for product_id, quantity in cart.items():
        product = Product.query.get(int(product_id))

        # ❌ FINAL STOCK CHECK
        if not product or product.stock_quantity < quantity:
            flash(
                f"Product '{product.name}' is out of stock or insufficient quantity.",
                "danger"
            )
            return redirect(url_for("main.cart"))

        item_total = product.price * quantity
        total_price += item_total

        # 🔻 DECREASE STOCK
        product.stock_quantity -= quantity

        order_item = OrderItem(
            order_id=order.order_id,
            product_id=product.product_id,
            quantity=quantity,
            price_per_unit=product.price
        )
        db.session.add(order_item)

    # ✅ UPDATE ORDER TOTAL
    order.total_amount = total_price
    db.session.commit()

    # ✅ CLEAR CART
    session.pop("cart", None)

    flash("Your order has been placed successfully!", "success")
    return redirect(url_for("main.orders"))




# ==================== ADMIN ROUTES ====================

# -------------------- ADMIN DASHBOARD --------------------
@main.route("/admin/dashboard")
@login_required
@admin_required
def admin_dashboard():
    total_products = Product.query.count()
    total_orders = Order.query.count()
    total_users = User.query.count()

    total_sales = db.session.query(
        db.func.sum(Order.total_amount)
    ).scalar() or 0

    low_stock_products = Product.query.filter(
        Product.stock_quantity <= 5
    ).count()

    forecast_data = [
            {"date": "Day 1", "predicted_sales": 10},
            {"date": "Day 2", "predicted_sales": 15},
            {"date": "Day 3", "predicted_sales": 8},
            {"date": "Day 4", "predicted_sales": 20},
            {"date": "Day 5", "predicted_sales": 12},
     ]

    

    return render_template(
        "admin_dashboard.html",
        total_products=total_products,
        total_orders=total_orders,
        total_users=total_users,
        total_sales=total_sales,
        low_stock_products=low_stock_products,
        forecast_data=forecast_data
    )

# -------------------- ADD PRODUCT --------------------
@main.route("/admin/product/new", methods=["GET", "POST"])
@login_required
@admin_required
def add_product():
    form = ProductForm()
    if form.validate_on_submit():
        product = Product(
            name=form.name.data,
            description=form.description.data,
            price=form.price.data,
            stock_quantity=form.stock_quantity.data,
            category=form.category.data,
            image_url=form.image_url.data
        )
        db.session.add(product)
        db.session.commit()
        flash("Product added!", "success")
        return redirect(url_for("main.admin_dashboard"))

    return render_template("add_product.html", form=form)



# -------------------- ADMIN USERS --------------------
@main.route("/admin/users")
@login_required
@admin_required
def admin_users():
    users = User.query.all()
    return render_template("admin_users.html", users=users)
@main.route("/admin/user/<int:user_id>")
@login_required
@admin_required
def admin_user_detail(user_id):
    user = User.query.get_or_404(user_id)

    orders = Order.query.filter_by(user_id=user.user_id)\
        .order_by(Order.order_date.desc()).all()

    total_orders = len(orders)

    total_spent = db.session.query(
        db.func.sum(Order.total_amount)
    ).filter_by(user_id=user.user_id).scalar() or 0

    return render_template(
        "admin_user_detail.html",
        user=user,
        orders=orders,
        total_orders=total_orders,
        total_spent=total_spent
    )


# -------------------- PROFILE --------------------
@main.route("/profile")
@login_required
def profile():
    user = current_user

    total_orders = Order.query.filter_by(user_id=user.user_id).count()
    total_spent = db.session.query(
        db.func.sum(Order.total_amount)
    ).filter_by(user_id=user.user_id).scalar() or 0

    return render_template(
        "profile.html",
        user=user,
        total_orders=total_orders,
        total_spent=total_spent
    )
@main.route("/admin/products")
@login_required
@admin_required
def admin_products():
    products = Product.query.all()
    return render_template("admin_products.html", products=products)

@main.route("/admin/orders")
@login_required
@admin_required
def admin_orders():
    orders = Order.query.order_by(Order.order_date.desc()).all()
    return render_template("admin_orders.html", orders=orders)
@main.route("/admin/sales")
@login_required
@admin_required
def admin_sales():
    orders = Order.query.all()

    total_sales = db.session.query(
        db.func.sum(Order.total_amount)
    ).scalar() or 0

    total_orders = len(orders)

    avg_order_value = 0
    if total_orders > 0:
        avg_order_value = total_sales / total_orders

    return render_template(
        "admin_sales.html",
        total_sales=total_sales,
        total_orders=total_orders,
        avg_order_value=round(avg_order_value, 2),
        orders=orders
    )
@main.route("/admin/order/<int:order_id>/status", methods=["POST"])
@login_required
@admin_required
def update_order_status(order_id):
    order = Order.query.get_or_404(order_id)
    new_status = request.form.get("status")

    order.status = new_status
    db.session.commit()

    flash("Order status updated successfully!", "success")
    return redirect(url_for("main.admin_orders"))

@main.route("/admin/low-stock")
@login_required
@admin_required
def admin_low_stock():
    low_stock_products = Product.query.filter(
        Product.stock_quantity <= 5
    ).all()

    return render_template(
        "admin_low_stock.html",
        products=low_stock_products
    )
