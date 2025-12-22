from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, BooleanField, TextAreaField, IntegerField, DecimalField, SelectField
from wtforms.validators import DataRequired, Length, Email, EqualTo, ValidationError, NumberRange
from .models import User


class CheckoutForm(FlaskForm):
    address = TextAreaField('Shipping Address', validators=[DataRequired()])
    submit = SubmitField('Place Order')