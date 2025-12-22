import pandas as pd
from sklearn.linear_model import LinearRegression
from datetime import datetime, timedelta
from .. import db
from ..models import Order

def get_sales_forecast():
    try:
        # Database mathi badha orders fetch karo
        orders = Order.query.all()
        if len(orders) < 2:
            return None # Aagahi mate ochhama ochho 2 divas no data joiye

        # DataFrame banavo
        data = [{'date': order.order_date.date(), 'sales': float(order.total_amount)} for order in orders]
        df = pd.DataFrame(data)
        
        # Date pramane sales ne group karo
        daily_sales = df.groupby('date')['sales'].sum().reset_index()
        
        if len(daily_sales) < 2:
            return None

        # Model mate data taiyar karo
        daily_sales['day_num'] = (daily_sales['date'] - daily_sales['date'].min()).dt.days
        
        X = daily_sales[['day_num']]
        y = daily_sales['sales']

        # Linear Regression model ne train karo
        model = LinearRegression()
        model.fit(X, y)

        # Aavta 30 divas mate aagahi karo
        last_day_num = X['day_num'].max()
        future_days = pd.DataFrame({'day_num': range(last_day_num + 1, last_day_num + 31)})
        predictions = model.predict(future_days)

        # Result taiyar karo
        last_date = daily_sales['date'].max()
        future_dates = [(last_date + timedelta(days=i)).strftime('%b %d') for i in range(1, 31)]

        return {'days': future_dates, 'predictions': [round(p, 2) for p in predictions]}
    except Exception as e:
        print(f"Error in forecasting: {e}")
        return None
