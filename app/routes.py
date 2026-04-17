from flask import render_template, url_for, flash, redirect, request, Blueprint, session
from . import db, bcrypt
from .forms import RegistrationForm, LoginForm, ProductForm, ReviewForm
from .models import Coupon, User, Product, Order, OrderItem, Review
from flask_login import login_user, current_user, logout_user, login_required
from functools import wraps
from io import BytesIO
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from decimal import Decimal
from flask import send_file
from datetime import datetime
from sqlalchemy import func
from datetime import datetime, timedelta
from reportlab.platypus import Image
from reportlab.lib import utils
import os


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
            user_id=current_user.user_id,
            product_id=product.product_id
            )
        
        db.session.add(review)
        db.session.commit()
        flash("Review added!", "success")
        return redirect(url_for("main.product_detail", product_id=product_id))

    reviews = Review.query.filter_by(
        product_id=product_id
    ).order_by(Review.created_at.desc()).all()
    review_count = len(reviews)

    if review_count > 0:
        avg_rating = round(
        sum([r.rating for r in reviews]) / review_count,
        1
    )
    else:
        avg_rating = 0


    return render_template(
    "product_detail.html",
    product=product,
    form=form,
    reviews=reviews,
    review_count=review_count,
    avg_rating=avg_rating
)
@main.route("/review/<int:review_id>/edit", methods=["GET", "POST"])
@login_required
def edit_review(review_id):
    review = Review.query.get_or_404(review_id)

    # 🔒 security: only owner
    if review.user_id != current_user.user_id:
        flash("Unauthorized access", "danger")
        return redirect(url_for("main.home"))

    form = ReviewForm()

    if form.validate_on_submit():
        review.rating = form.rating.data
        review.comment = form.comment.data
        db.session.commit()

        flash("Review updated!", "success")
        return redirect(
            url_for("main.product_detail", product_id=review.product_id)
        )

    # form pre-fill
    form.rating.data = review.rating
    form.comment.data = review.comment

    return render_template("edit_review.html", form=form)


@main.route("/review/<int:review_id>/delete", methods=["POST"])
@login_required
def delete_review(review_id):
    review = Review.query.get_or_404(review_id)

    # 🔒 only owner
    if review.user_id != current_user.user_id:
        flash("Unauthorized action", "danger")
        return redirect(url_for("main.home"))

    product_id = review.product_id

    db.session.delete(review)
    db.session.commit()

    flash("Review deleted!", "info")
    return redirect(
        url_for("main.product_detail", product_id=product_id)
    )



# -------------------- CART --------------------
@main.route("/add_to_cart/<int:product_id>", methods=["POST"])
@login_required
def add_to_cart(product_id):
    product = Product.query.get_or_404(product_id)

    quantity = int(request.form.get("quantity", 1))

    cart = session.get("cart", {})
    current_qty = cart.get(str(product_id), 0)

    new_total = current_qty + quantity

    # ✅ FIX: Total quantity check
    if new_total > product.stock_quantity:
        flash(f"Only {product.stock_quantity} item(s) available in stock.", "danger")
        return redirect(url_for("main.product_detail", product_id=product_id))

    cart[str(product_id)] = new_total
    session["cart"] = cart

    flash("Product added to cart!", "success")
    return redirect(url_for("main.cart"))
@main.route("/orders")
@login_required
def orders():

    status_filter = request.args.get("status")

    query = Order.query.filter_by(user_id=current_user.user_id)

    if status_filter and status_filter != "All":
        query = query.filter_by(status=status_filter)

    user_orders = query.order_by(Order.order_date.desc()).all()

    return render_template(
        "orders.html",
        orders=user_orders,
        selected_status=status_filter or "All"
    )
@main.route("/order/invoice/<int:order_id>")
@login_required
def download_invoice(order_id):

    order = Order.query.get_or_404(order_id)

    if order.user_id != current_user.user_id:
        flash("Unauthorized access", "danger")
        return redirect(url_for("main.orders"))

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=30,
        bottomMargin=30
    )

    elements = []
    styles = getSampleStyleSheet()

    # -------- LOGO --------
    logo_path = os.path.join("app", "static", "images", "logo.png")

    logo = Image(logo_path)
    logo.drawHeight = 50
    logo.drawWidth = 150

    elements.append(logo)
    elements.append(Spacer(1, 15))
   
    # =============================
    # BILL TO
    # =============================
    elements.append(Paragraph("<b>Bill To:</b>", styles["Heading3"]))
    elements.append(Spacer(1, 10))
    elements.append(Paragraph(f"<b>Name:</b> {current_user.username}", styles["Normal"]))
    elements.append(Paragraph(f"<b>Email:</b> {current_user.email}", styles["Normal"]))
    elements.append(Paragraph(f"<b>Address:</b> {order.shipping_address}", styles["Normal"]))
    elements.append(Spacer(1, 15))



    # =============================
    # ORDER INFO TABLE
    # =============================
    order_info_data = [
        ["Order ID", str(order.order_id)],
        ["Order Date", order.order_date.strftime("%d %b %Y")],
        ["Status", order.status]
    ]

    order_table = Table(order_info_data, colWidths=[120, 250])
    order_table.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
        ("BACKGROUND", (0,0), (0,-1), colors.whitesmoke),
        ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE", (0,0), (-1,-1), 10),
    ]))

    elements.append(order_table)
    elements.append(Spacer(1, 25))

    # =============================
    # PRODUCT TABLE
    # =============================
    data = [["Product", "Qty", "Unit Price (₹)", "Total (₹)"]]

    grand_total = Decimal(0)

    for item in order.items:
        product = Product.query.get(item.product_id)
        if not product:
            continue

        item_total = item.price_per_unit * item.quantity
        grand_total += item_total

        data.append([
            product.name,
            str(item.quantity),
            f"{item.price_per_unit:.2f}",
            f"{item_total:.2f}"
        ])

    # Grand total row
    data.append(["", "", "Grand Total", f"{grand_total:.2f}"])

    product_table = Table(data, colWidths=[200, 60, 100, 100])
    product_table.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
        ("ALIGN", (1,1), (-1,-1), "CENTER"),
        ("BACKGROUND", (-2,-1), (-1,-1), colors.whitesmoke),
        ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
    ]))

    elements.append(product_table)
    elements.append(Spacer(1, 30))

    # =============================
    # FOOTER
    # =============================
    elements.append(Paragraph("Thank you for shopping with CommerceIQ AI.", styles["Normal"]))
    

    doc.build(elements)
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"Invoice_Order_{order.order_id}.pdf",
        mimetype="application/pdf"
    )

@main.route("/order/cancel/<int:order_id>", methods=["POST"])
@login_required
def cancel_order(order_id):

    order = Order.query.get_or_404(order_id)

    # 🔐 Security check (only owner)
    if order.user_id != current_user.user_id:
        flash("Unauthorized action.", "danger")
        return redirect(url_for("main.orders"))

    # ❌ Cannot cancel if shipped
    if order.status in ["Shipped", "Out for Delivery", "Delivered"]:
        flash("Order cannot be cancelled now.", "danger")
        return redirect(url_for("main.orders"))

    # ✅ RESTORE STOCK
    for item in order.items:
        product = Product.query.get(item.product_id)
        if product:
            product.stock_quantity += item.quantity

    # ✅ UPDATE STATUS
    order.status = "Cancelled"
    db.session.commit()

    flash("Order cancelled successfully.", "success")
    return redirect(url_for("main.orders"))



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
                "id": product.product_id,
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
from datetime import date, timedelta, datetime

@main.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():

    cart = session.get("cart", {})

    if not cart:
        flash("Your cart is empty.", "info")
        return redirect(url_for("main.home"))

    total_price = 0

    # ---------------- CALCULATE TOTAL ----------------
    for product_id, quantity in cart.items():
        product = Product.query.get(int(product_id))
        if product:
            total_price += product.price * quantity

    # ---------------- POST REQUEST ----------------
    if request.method == "POST":

        shipping_address = request.form.get("shipping_address")
        coupon_code = request.form.get("coupon_code")
        payment_method = request.form.get("payment_method")

        if not shipping_address:
            flash("Shipping address is required!", "danger")
            return redirect(url_for("main.checkout"))

        discount_amount = 0

        # ---------------- COUPON VALIDATION ----------------
        if coupon_code:

            coupon = Coupon.query.filter_by(
                code=coupon_code,
                user_id=current_user.user_id,
                is_used=False
            ).first()

            if coupon:

                if coupon.expiry_date and coupon.expiry_date < datetime.utcnow():
                    flash("Coupon expired!", "danger")
                    return redirect(url_for("main.checkout"))

                discount_amount = (total_price * coupon.discount_percent) / 100
                total_price -= discount_amount

                coupon.is_used = True
                db.session.commit()

                flash(f"{coupon.discount_percent}% discount applied!", "success")

            else:
                flash("Invalid coupon code!", "danger")
                return redirect(url_for("main.checkout"))

        # ---------------- DELIVERY LOGIC ----------------
        base_days = 5
        city = "Ahmedabad"

        if payment_method == "COD":
            base_days += 2

        metro_cities = ["Ahmedabad", "Mumbai", "Delhi", "Bangalore"]
        if city in metro_cities:
            base_days -= 1

        estimated_delivery = date.today() + timedelta(days=base_days)

        # ---------------- FAKE PAYMENT ----------------
        if payment_method in ["UPI", "Card"]:

            session["temp_order"] = {
                "shipping_address": shipping_address,
                "total_price": total_price,
                "payment_method": payment_method,
                "estimated_delivery": str(estimated_delivery)
            }

            return redirect(url_for("main.fake_payment"))

        # ---------------- CREATE ORDER ----------------
        order = Order(
            user_id=current_user.user_id,
            total_amount=total_price,
            status="Pending",
            shipping_address=shipping_address,
            payment_method=payment_method,
            city=city,
            estimated_delivery=estimated_delivery
        )

        db.session.add(order)
        db.session.commit()

        # ---------------- PROCESS ITEMS ----------------
        for product_id, quantity in cart.items():

            product = Product.query.get(int(product_id))

            # 🔥 FIX: strict validation
            if not product:
                flash("Product not found!", "danger")
                return redirect(url_for("main.cart"))

            if quantity > product.stock_quantity:
                flash(f"Only {product.stock_quantity} items available for {product.name}", "danger")
                return redirect(url_for("main.cart"))

            product.stock_quantity -= quantity

            order_item = OrderItem(
                order_id=order.order_id,
                product_id=product.product_id,
                quantity=quantity,
                price_per_unit=product.price
            )

            db.session.add(order_item)

        db.session.commit()

        session.pop("cart", None)

        flash("Order placed successfully!", "success")
        return redirect(url_for("main.orders"))

    # ---------------- GET ----------------
    return render_template(
        "checkout.html",
        total_price=total_price
    )

@main.route("/fake-payment", methods=["GET", "POST"])
@login_required
def fake_payment():

    temp_order = session.get("temp_order")

    if not temp_order:
        flash("Invalid payment session.", "danger")
        return redirect(url_for("main.checkout"))

    if request.method == "POST":

        # ---------------- CREATE ORDER AFTER FAKE PAYMENT ----------------
        order = Order(
            user_id=current_user.user_id,
            total_amount=temp_order["total_price"],
            status="Confirmed",
            shipping_address=temp_order["shipping_address"],
            payment_method=temp_order["payment_method"],
            city="Ahmedabad",
            estimated_delivery=datetime.strptime(
                temp_order["estimated_delivery"], "%Y-%m-%d"
            )
        )

        db.session.add(order)
        db.session.commit()

        cart = session.get("cart", {})

        for product_id, quantity in cart.items():

            product = Product.query.get(int(product_id))

            if not product or product.stock_quantity < quantity:
                flash("Product out of stock!", "danger")
                return redirect(url_for("main.cart"))

            product.stock_quantity -= quantity

            order_item = OrderItem(
                order_id=order.order_id,
                product_id=product.product_id,
                quantity=quantity,
                price_per_unit=product.price
            )

            db.session.add(order_item)

        db.session.commit()

        session.pop("cart", None)
        session.pop("temp_order", None)

        flash("Payment successful! Order confirmed.", "success")
        return redirect(url_for("main.orders"))

    return render_template(
        "fake_payment.html",
        method=temp_order["payment_method"],
        total=temp_order["total_price"]
    )
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
        func.sum(Order.total_amount)
    ).scalar() or 0

    cancelled_orders = Order.query.filter_by(status="Cancelled").count()

    # 🏆 MOST SOLD PRODUCT
    
    most_sold = db.session.query(
    Product.product_id,
    Product.name,
    func.sum(OrderItem.quantity).label("total_qty")
    ).join(OrderItem, Product.product_id == OrderItem.product_id) \
    .group_by(Product.product_id) \
    .order_by(func.sum(OrderItem.quantity).desc()) \
    .first()

    if most_sold:
        most_sold_id = most_sold[0]
        most_sold_product = most_sold[1]
        most_sold_qty = most_sold[2]
    else:
        most_sold_id = None
        most_sold_product = "No Data"
        most_sold_qty = 0


    # 📈 SALES GROWTH
    today = datetime.now()
    last_7_days = today - timedelta(days=7)
    previous_7_days = today - timedelta(days=14)

    current_sales = db.session.query(
        func.sum(Order.total_amount)
    ).filter(
        Order.order_date >= last_7_days
    ).scalar() or 0

    previous_sales = db.session.query(
        func.sum(Order.total_amount)
    ).filter(
        Order.order_date >= previous_7_days,
        Order.order_date < last_7_days
    ).scalar() or 0

    sales_growth = 0
    if previous_sales > 0:
        sales_growth = round(
            ((current_sales - previous_sales) / previous_sales) * 100,
            2
        )

    # ⚠️ LOW STOCK COUNT
    low_stock_products = Product.query.filter(
        Product.stock_quantity <= 5
    ).count()

    # 📊 LAST 7 DAYS CHART
    sales_data = db.session.query(
        func.date(Order.order_date),
        func.sum(Order.total_amount),
        func.count(Order.order_id)
    ).filter(
        Order.order_date >= last_7_days
    ).group_by(
        func.date(Order.order_date)
    ).all()

    chart_labels = []
    chart_sales = []
    chart_orders = []

    for row in sales_data:
        chart_labels.append(row[0].strftime("%d %b"))
        chart_sales.append(float(row[1]))
        chart_orders.append(row[2])

    # ==============================
    # 📈 SALES FORECAST (Next 7 Days)
    # ==============================

    last_30_days = datetime.now() - timedelta(days=30)

    sales_last_30 = db.session.query(
        func.date(Order.order_date),
        func.sum(Order.total_amount)
    ).filter(
        Order.order_date >= last_30_days
    ).group_by(
        func.date(Order.order_date)
    ).all()

    daily_sales = [float(row[1]) for row in sales_last_30]

    forecast_labels = []
    forecast_values = []

    if daily_sales:
        avg_daily_sales = sum(daily_sales) / len(daily_sales)

        for i in range(1, 8):
            future_date = datetime.now() + timedelta(days=i)
            forecast_labels.append(future_date.strftime("%d %b"))
            forecast_values.append(round(avg_daily_sales * 1.05, 2))  # 5% growth assumption
    # 🔮 SIMPLE FORECAST (demo growth)
    forecast_labels = []
    forecast_values = []

    if chart_sales:
        last_value = chart_sales[-1]
        for i in range(1, 6):
            forecast_labels.append(f"F{i}")
            forecast_values.append(round(last_value * (1 + 0.05 * i), 2))

    # ==============================
    # 🚨 HIGH RISK STOCK CHECK
    # ==============================

    high_risk_count = 0

    last_30_days = datetime.now() - timedelta(days=30)

    all_products = Product.query.all()

    for product in all_products:

        total_sold = db.session.query(
            func.sum(OrderItem.quantity)
        ).join(Order, Order.order_id == OrderItem.order_id) \
        .filter(
            OrderItem.product_id == product.product_id,
            Order.order_date >= last_30_days
        ).scalar() or 0

        avg_daily_sales = total_sold / 30 if total_sold > 0 else 0

        if avg_daily_sales > 0:
            days_left = product.stock_quantity / avg_daily_sales

            if days_left <= 5:
                high_risk_count += 1

    # ==============================
    # 🚨 SMART ALERT MESSAGE
    # ==============================

    alert_message = None

    if high_risk_count > 0:
        alert_message = (
            f"{high_risk_count} product(s) may run out of stock within 5 days. "
            "Immediate action recommended."
        )
     

    return render_template(
        "admin_dashboard.html",
        total_products=total_products,
        total_orders=total_orders,
        total_users=total_users,
        total_sales=total_sales,
        cancelled_orders=cancelled_orders,
        low_stock_products=low_stock_products,
        most_sold_product=most_sold_product,
        most_sold_id=most_sold_id,
        sales_growth=sales_growth,
        chart_labels=chart_labels,
        chart_sales=chart_sales,
        chart_orders=chart_orders,
        forecast_labels=forecast_labels,
        forecast_values=forecast_values,
        high_risk_count=high_risk_count,
        alert_message=alert_message

     )
@main.route("/admin/analytics")
@login_required
@admin_required
def admin_analytics():

    total_products = Product.query.count()
    total_orders = Order.query.count()

    total_sales = db.session.query(
        func.sum(Order.total_amount)
    ).scalar() or 0

    # ==============================
    # 📈 SALES GROWTH
    # ==============================
    today = datetime.now()
    last_7_days = today - timedelta(days=7)
    previous_7_days = today - timedelta(days=14)

    current_sales = db.session.query(
        func.sum(Order.total_amount)
    ).filter(Order.order_date >= last_7_days).scalar() or 0

    previous_sales = db.session.query(
        func.sum(Order.total_amount)
    ).filter(
        Order.order_date >= previous_7_days,
        Order.order_date < last_7_days
    ).scalar() or 0

    sales_growth = 0
    if previous_sales > 0:
        sales_growth = round(
            ((current_sales - previous_sales) / previous_sales) * 100, 2
        )

    # ==============================
    # 📊 DAILY AVG + PEAK DAY
    # ==============================
    sales_data = db.session.query(
        func.date(Order.order_date),
        func.sum(Order.total_amount),
        func.count(Order.order_id)
    ).group_by(func.date(Order.order_date)).all()

    chart_labels = []
    chart_sales = []
    chart_orders = []

    peak_day = "No Data"
    max_sale = 0

    for row in sales_data:
        chart_labels.append(row[0].strftime("%d %b"))
        chart_sales.append(float(row[1]))
        chart_orders.append(row[2])

        if row[1] > max_sale:
            max_sale = row[1]
            peak_day = row[0].strftime("%d %b")

    daily_avg_sales = 0
    if chart_sales:
        daily_avg_sales = round(sum(chart_sales) / len(chart_sales), 2)

    return render_template(
        "admin_analytics.html",
        total_products=total_products,
        total_orders=total_orders,
        total_sales=total_sales,
        sales_growth=sales_growth,
        daily_avg_sales=daily_avg_sales,
        peak_day=peak_day,
        chart_labels=chart_labels,
        chart_sales=chart_sales,
        chart_orders=chart_orders
    )


@main.route("/admin/report/users")
@login_required
@admin_required
def admin_users_report():

    from_date = request.args.get("from_date")
    to_date = request.args.get("to_date")

    query = Order.query

    if from_date and to_date:
        query = query.filter(
            Order.order_date.between(from_date, to_date)
        )

    orders = query.order_by(Order.order_date.desc()).all()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []
    styles = getSampleStyleSheet()

    elements.append(Paragraph("<b>CommerceIQ AI - Admin Report</b>", styles["Title"]))
    elements.append(Spacer(1, 15))

    elements.append(Paragraph(
        f"Date Range: {from_date} to {to_date}",
        styles["Normal"]
    ))
    elements.append(Spacer(1, 20))

    data = [["Order ID", "User", "Date", "Status", "Amount (Rs)"]]

    total_amount = Decimal(0)

    for order in orders:
        user = User.query.get(order.user_id)
        total_amount += order.total_amount

        data.append([
            str(order.order_id),
            user.username if user else "Unknown",
            order.order_date.strftime("%d %b %Y"),
            order.status,
            f"{order.total_amount:.2f}"
        ])

    data.append(["", "", "", "Total", f"{total_amount:.2f}"])

    table = Table(data, colWidths=[60, 90, 90, 90, 80])
    table.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
        ("ALIGN", (-1,1), (-1,-1), "RIGHT"),
    ]))

    elements.append(table)

    doc.build(elements)
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="Admin_User_Report.pdf",
        mimetype="application/pdf"
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
            image_url=form.image_url.data,
            discount_percent=form.discount_percent.data or 0
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


    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    users_query = User.query

    if start_date and end_date:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")

        users_query = users_query.filter(
            User.created_at.between(start, end)
        )

    users = users_query.order_by(User.created_at.desc()).all()

    return render_template(
        "admin_users.html",
        users=users,
        start_date=start_date,
        end_date=end_date
    )
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
@main.route("/admin/users/pdf")
@login_required
@admin_required
def users_pdf():

    

    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    users_query = User.query

    if start_date and end_date:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        users_query = users_query.filter(
            User.created_at.between(start, end)
        )

    users = users_query.order_by(User.created_at.desc()).all()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []
    styles = getSampleStyleSheet()

    # -------- LOGO --------
    logo_path = os.path.join("app", "static", "images", "logo.png")

    logo = Image(logo_path)
    logo.drawHeight = 50
    logo.drawWidth = 150

    elements.append(logo)
    elements.append(Spacer(1, 15))

    data = [["Username", "Email", "Role", "Registered On"]]

    for user in users:
        data.append([
            user.username,
            user.email,
            user.role,
            user.created_at.strftime("%d %b %Y")
        ])

    table = Table(data)
    table.setStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
        ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
    ])

    elements.append(table)

    doc.build(elements)
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="Users_Report.pdf",
        mimetype="application/pdf"
    )

@main.route("/admin/top-products")
@login_required
@admin_required
def admin_top_products():

    top_products = db.session.query(
        Product.product_id,
        Product.name,
        Product.stock_quantity,
        func.sum(OrderItem.quantity).label("total_sold")
    ).join(
        OrderItem, Product.product_id == OrderItem.product_id
    ).group_by(
        Product.product_id
    ).order_by(
        func.sum(OrderItem.quantity).desc()
    ).all()

    return render_template(
        "admin_top_products.html",
        top_products=top_products
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
    low_stock = request.args.get("low_stock")

    if low_stock:
        products = Product.query.filter(Product.stock_quantity <= 5).all()
    else:
        products = Product.query.all()

    return render_template(
        "admin_products.html",
        products=products,
        low_stock=low_stock
    )

@main.route("/admin/orders")
@login_required
@admin_required
def admin_orders():

    status = request.args.get("status")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    orders_query = Order.query

    # 🔹 Status filter
    if status:
        orders_query = orders_query.filter_by(status=status)

    # 🔹 Date filter
    if start_date and end_date:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        orders_query = orders_query.filter(
            Order.order_date.between(start, end)
        )

    orders = orders_query.order_by(Order.order_date.desc()).all()

    return render_template(
        "admin_orders.html",
        orders=orders,
        status=status,
        start_date=start_date,
        end_date=end_date
    )
@main.route("/admin/orders/pdf")
@login_required
@admin_required
def orders_pdf():

    status = request.args.get("status")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    orders_query = Order.query

    if status:
        orders_query = orders_query.filter_by(status=status)

    if start_date and end_date:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        orders_query = orders_query.filter(
            Order.order_date.between(start, end)
        )

    orders = orders_query.order_by(Order.order_date.desc()).all()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []
    styles = getSampleStyleSheet()

    # -------- LOGO --------
    logo_path = os.path.join("app", "static", "images", "logo.png")

    logo = Image(logo_path)
    logo.drawHeight = 50
    logo.drawWidth = 150

    elements.append(logo)
    elements.append(Spacer(1, 15))

    data = [["Order ID", "User", "Date", "Status", "Amount (Rs)"]]

    for order in orders:
        user = User.query.get(order.user_id)
        data.append([
            str(order.order_id),
            user.username if user else "N/A",
            order.order_date.strftime("%d %b %Y"),
            order.status,
            f"{order.total_amount:.2f}"
        ])

    table = Table(data)
    table.setStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
        ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
    ])

    elements.append(table)

    doc.build(elements)
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="Orders_Report.pdf",
        mimetype="application/pdf"
    )


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
@main.route("/admin/order/update/<int:order_id>", methods=["POST"])
@login_required
@admin_required
def update_order_status(order_id):
    order = Order.query.get_or_404(order_id)

    new_status = request.form.get("status")

    allowed_status = [
        "Pending",
        "Confirmed",
        "Shipped",
        "Out for Delivery",
        "Delivered"
    ]

    if new_status not in allowed_status:
        flash("Invalid status", "danger")
        return redirect(url_for("main.admin_orders"))

    order.status = new_status
    db.session.commit()

    flash("Order status updated!", "success")
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
@main.route("/admin/orders/cancelled")
@login_required
@admin_required
def admin_cancelled_orders():
    cancelled_orders = Order.query.filter_by(status="Cancelled") \
                                  .order_by(Order.order_date.desc()) \
                                  .all()

    return render_template(
        "admin_cancelled_orders.html",
        orders=cancelled_orders
    )
@main.route("/admin/category-analytics")
@login_required
@admin_required
def admin_category_analytics():

    category_data = db.session.query(
        Product.category,
        func.count(Product.product_id),
        func.sum(OrderItem.quantity * OrderItem.price_per_unit)
    ).join(OrderItem, Product.product_id == OrderItem.product_id) \
     .group_by(Product.category).all()

    return render_template(
        "admin_category_analytics.html",
        category_data=category_data
    )


@main.route("/admin/ai-insights")
@login_required
@admin_required
def admin_ai_insights():

    # 🔥 IMPORTANT — DEFINE FILTER
    filter_type = request.args.get("type")

    risk_products = []

    last_30_days = datetime.now() - timedelta(days=30)

    product_sales = db.session.query(
        Product.product_id,
        Product.name,
        Product.stock_quantity,
        func.sum(OrderItem.quantity).label("total_sold")
    ).join(OrderItem, Product.product_id == OrderItem.product_id) \
     .join(Order, Order.order_id == OrderItem.order_id) \
     .filter(Order.order_date >= last_30_days) \
     .group_by(Product.product_id).all()

    for product in product_sales:

        product_id = product[0]
        name = product[1]
        stock = product[2]
        total_sold = product[3] or 0

        avg_daily_sales = total_sold / 30 if total_sold > 0 else 0

        # ==============================
        # ✅  RISK CLASSIFICATION
        # ==============================

        if stock == 0:
            risk = "High"
            days_left = 0

        elif avg_daily_sales == 0:
            risk = "Low"
            days_left = "No Sales"

        else:
            days_left = round(stock / avg_daily_sales, 1)

            if days_left <= 5:
                risk = "High"
            elif days_left <= 15:
                risk = "Medium"
            else:
                risk = "Low"

       

        # 🔥 APPLY FILTER AFTER RISK CALCULATION
        if filter_type == "high" and risk != "High":
            continue

        risk_products.append({
            "name": name,
            "stock": stock,
            "avg_daily_sales": round(avg_daily_sales, 2),
            "days_left": days_left,
            "risk": risk
        })

    return render_template(
        "admin_ai_insights.html",
        risk_products=risk_products,
        filter_type=filter_type,
    )

@main.app_context_processor
def inject_coupon_count():

    if current_user.is_authenticated and current_user.role != "admin":
        coupon_count = Coupon.query.filter_by(
            user_id=current_user.user_id,
            is_used=False
        ).count()
    else:
        coupon_count = 0

    return dict(coupon_count=coupon_count)
@main.route("/admin/customer-intelligence")
@login_required
@admin_required
def admin_customer_intelligence():

    import random   
    import string

    filter_type = request.args.get("type")

    customers = User.query.filter_by(role="customer").all()

    vip_customers = []
    regular_customers = []
    inactive_customers = []

    last_30_days = datetime.now() - timedelta(days=30)

    for customer in customers:

        orders = Order.query.filter_by(user_id=customer.user_id).all()
        total_spent = sum(order.total_amount for order in orders)

        last_order = Order.query.filter_by(user_id=customer.user_id) \
            .order_by(Order.order_date.desc()).first()

        if total_spent >= 50000:
            category = "vip"
            vip_customers.append((customer, total_spent))

        elif not last_order or last_order.order_date < last_30_days:
            category = "inactive"
            inactive_customers.append((customer, total_spent))

        else:
            category = "regular"
            regular_customers.append((customer, total_spent))

    # Filter logic
    if filter_type == "vip":
        display_list = vip_customers
    elif filter_type == "inactive":
        display_list = inactive_customers
    elif filter_type == "regular":
        display_list = regular_customers
    else:
        display_list = None

    predicted_customers = []

    for customer in customers:

        user_orders = Order.query.filter_by(user_id=customer.user_id) \
            .order_by(Order.order_date.asc()).all()

        if len(user_orders) >= 3:

            gaps = []
            for i in range(1, len(user_orders)):
                gap = (user_orders[i].order_date - user_orders[i-1].order_date).days
                gaps.append(gap)

            avg_gap = sum(gaps) / len(gaps)

            last_order_date = user_orders[-1].order_date
            days_since_last_order = (datetime.now() - last_order_date).days

            # Prediction rule
            if days_since_last_order >= avg_gap * 0.8:
                predicted_customers.append({
                    "customer": customer,
                    "avg_gap": round(avg_gap, 1),
                    "days_since_last_order": days_since_last_order
                })
    churn_risk_customers = []
    clv_data = []

    for customer in customers:

        user_orders = Order.query.filter_by(user_id=customer.user_id) \
            .order_by(Order.order_date.asc()).all()

        total_orders = len(user_orders)

        if total_orders == 0:
            continue

        total_spent = sum(order.total_amount for order in user_orders)
        avg_order_value = total_spent / total_orders

        clv = round(avg_order_value * total_orders, 2)

        clv_data.append({
            "customer": customer,
            "clv": clv,
            "total_orders": total_orders
        })
        
        # Sort and take top 5 here (NOT in template)
        clv_data = sorted(clv_data, key=lambda x: x["clv"], reverse=True)[:5]

        # 🔴 Churn Risk Logic
        if total_orders >= 2:

            gaps = []
            for i in range(1, total_orders):
                gap = (user_orders[i].order_date - user_orders[i-1].order_date).days
                gaps.append(gap)

            avg_gap = sum(gaps) / len(gaps)

            last_order_date = user_orders[-1].order_date
            days_since_last = (datetime.now() - last_order_date).days

            if days_since_last > avg_gap * 2:
                churn_risk_customers.append(customer)

    coupon_recommendations = []

    for item in clv_data:

        customer = item["customer"]
        clv = item["clv"]

        coupon_percent = 5

        if clv > 10000:
            coupon_percent = 20
        elif clv > 5000:
            coupon_percent = 15
        elif clv > 2000:
            coupon_percent = 10

        if customer in churn_risk_customers:
                coupon_percent = 20

                # 🔥 Generate random coupon code
                random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=3))
                coupon_code = f"AI{coupon_percent}{random_part}"

                coupon_recommendations.append({
                    "customer": customer,
                    "clv": clv,
                    "coupon_percent": coupon_percent,
                    "coupon_code": coupon_code,
                    "sent": False
                })

    return render_template(
        "admin_customer_intelligence.html",
        vip_customers=vip_customers,
        regular_customers=regular_customers,
        inactive_customers=inactive_customers,
        display_list=display_list,
        filter_type=filter_type,
        predicted_customers=predicted_customers,
        churn_risk_customers=churn_risk_customers,
        clv_data=clv_data,
        coupon_recommendations=coupon_recommendations
    )
@main.route("/admin/send-coupon/<int:user_id>/<coupon_code>/<int:discount>")
@login_required
@admin_required
def send_coupon(user_id, coupon_code, discount):

    user = User.query.get_or_404(user_id)

    expiry = datetime.utcnow() + timedelta(days=7)

    new_coupon = Coupon(
        code=coupon_code,
        discount_percent=discount,
        user_id=user.user_id,
        is_sent=True,
        expiry_date=expiry
    )

    db.session.add(new_coupon)
    db.session.commit()

    flash(f"Coupon {coupon_code} sent! Valid for 7 days.", "success")

    return redirect(url_for("main.admin_customer_intelligence"))

@main.route("/admin/coupons")
@login_required
@admin_required
def admin_coupons():

    coupons = Coupon.query.order_by(Coupon.created_at.desc()).all()

    return render_template("admin_coupons.html", coupons=coupons)

@main.route("/my-coupons")
@login_required
def my_coupons():

    coupons = Coupon.query.filter_by(
        user_id=current_user.user_id,
        is_used=False
    ).all()

    return render_template(
        "my_coupons.html",
        coupons=coupons
    )