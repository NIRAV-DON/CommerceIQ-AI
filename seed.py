from app import create_app, db
from app.models import Product, User, Order, OrderItem, Review
from sqlalchemy.sql import text

app = create_app()

def seed():
    with app.app_context():
        print("Starting database reset...")
        
        # 1. Foreign key checks ne thodi var bandh karo jethi deletion ma error na aave
        db.session.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
        
        # 2. Badha tables ne khali karo (Orders, Reviews badhu j)
        try:
            Review.query.delete()
            OrderItem.query.delete()
            Order.query.delete()
            Product.query.delete()
            # User.query.delete() # Jo tame user delete na karva mangta ho to aa line ne comment rakho
            
            db.session.commit()
            print("Database cleared successfully.")
        except Exception as e:
            db.session.rollback()
            print(f"Error while clearing data: {e}")
        finally:
            # 3. Foreign key checks ne farithi chalu kari do
            db.session.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))

        # 4. Sample Products umeravo
        print("Adding sample products...")
        p1 = Product(name="iPhone 15 Pro", description="Titanium design, A17 Pro chip.", price=134900, stock_quantity=10, category="Electronics")
        p2 = Product(name="MacBook Air M2", description="Strikingly thin and fast laptop.", price=114900, stock_quantity=5, category="Laptops")
        p3 = Product(name="Sony WH-1000XM5", description="Best noise canceling headphones.", price=29990, stock_quantity=15, category="Accessories")
        
        db.session.add_all([p1, p2, p3])
        db.session.commit()
        print("Success: 3 Sample Products added to MySQL!")

if __name__ == "__main__":
    seed()