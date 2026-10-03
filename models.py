from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    hourly_rate = db.Column(db.Float, nullable=False)
    tax_rate = db.Column(db.Float, default=0.15) # Default 15% tax
    upi_id = db.Column(db.String(120))
    payrolls = db.relationship('Payroll', backref='employee', lazy=True)

class Payroll(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    hours_worked = db.Column(db.Float, nullable=False)
    gross_pay = db.Column(db.Float, nullable=False)
    tax_deductions = db.Column(db.Float, nullable=False)
    net_pay = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default="PENDING") # PENDING, PROCESSED, FAILED
    processed_at = db.Column(db.DateTime, default=datetime.utcnow)