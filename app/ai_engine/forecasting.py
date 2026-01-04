import pandas as pd
from sklearn.linear_model import LinearRegression
from app.models import Order
from app import db
from datetime import timedelta

def get_sales_forecast(days=5):
    # 1️⃣ DB mathi sales data
    orders = db.session.query(
        Order.order_date,
        Order.total_amount
    ).all()

    if not orders:
        return []

    # 2️⃣ DataFrame banavo
    df = pd.DataFrame(orders, columns=["date", "sales"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.groupby(df["date"].dt.date).sum().reset_index()

    # 3️⃣ Date → number (ML mate)
    df["day"] = range(len(df))

    X = df[["day"]]
    y = df["sales"]

    # 4️⃣ Train model
    model = LinearRegression()
    model.fit(X, y)

    # 5️⃣ Future days predict
    future_days = [[len(df) + i] for i in range(days)]
    predictions = model.predict(future_days)

    # 6️⃣ Chart mate format
    forecast = []
    last_date = df["date"].iloc[-1]

    for i, value in enumerate(predictions):
        forecast.append({
            "date": str(last_date + timedelta(days=i + 1)),
            "predicted_sales": round(float(value), 2)
        })

    return forecast
