import pandas as pd
from app import db
from app.models import Order, OrderItem, Product
from itertools import combinations

def get_frequent_pairs():
    """
    Analyzes all orders to find pairs of products that are frequently bought together.
    """
    # Database mathi badha order items no data lado
    query = db.session.query(OrderItem.order_id, OrderItem.product_id).all()
    
    # Jo data na hoy to khaali list return karo
    if not query:
        return []

    # Pandas DataFrame banavo
    df = pd.DataFrame(query, columns=['order_id', 'product_id'])

    # Darek order ma kai kai products chhe teni yadi banavo
    order_products = df.groupby('order_id')['product_id'].apply(list)

    # Fakt e j order rakho jema 1 thi vadhare product hoy
    multi_item_orders = order_products[order_products.apply(len) > 1]

    # Darek order mathi products ni jodi (pairs) banavo
    pairs = multi_item_orders.apply(lambda x: list(combinations(sorted(x), 2)))

    # Badhi j jodi ne ek j list ma muko
    all_pairs = [pair for sublist in pairs for pair in sublist]

    # Jo koi jodi na mali hoy to khaali list return karo
    if not all_pairs:
        return []

    # Darek jodi ketli vakhat aavi e gano
    pair_counts = pd.Series(all_pairs).value_counts().reset_index()
    pair_counts.columns = ['pair', 'frequency']

    # Product IDs ne Product na naam sathe badlo
    product_names = {p.product_id: p.name for p in Product.query.all()}
    
    pair_counts['Product1'] = pair_counts['pair'].apply(lambda x: product_names.get(x[0]))
    pair_counts['Product2'] = pair_counts['pair'].apply(lambda x: product_names.get(x[1]))

    # Final result taiyar karo
    result = pair_counts[['Product1', 'Product2', 'frequency']]
    # Pandas na DataFrame ne Python ni dictionary ni list ma fervo
    final_result = result.rename(columns={'frequency': 'Frequency'}).to_dict('records')

    return final_result
