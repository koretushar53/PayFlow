from io import BytesIO
from urllib.parse import urlencode
from xml.sax.saxutils import escape

import qrcode
from flask import Flask, abort, flash, make_response, render_template, request, jsonify, redirect, send_file, url_for
from models import db, Employee, Payroll
from payroll_engine import calculate_paycheck
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

app = Flask(__name__)
# Configure SQLite with extended timeouts and connection limits for high concurrent traffic
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///payflow.db?timeout=30'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'payflow-secret-key-123'

db.init_app(app)

with app.app_context():
    db.create_all()
    employee_columns = {
        column["name"] for column in db.inspect(db.engine).get_columns("employee")
    }
    if "upi_id" not in employee_columns:
        db.session.execute(db.text("ALTER TABLE employee ADD COLUMN upi_id VARCHAR(120)"))
        db.session.commit()

# --- WEB UI ROUTES ---

@app.route("/")
def index():
    employees = Employee.query.all()
    payrolls = Payroll.query.order_by(Payroll.processed_at.desc()).limit(100).all()
    return render_template("index.html", employees=employees, payrolls=payrolls)


@app.route("/add-employee", methods=["POST"])
def add_employee():
    upi_id = request.form.get("upi_id", "").strip() or None
    if upi_id and "@" not in upi_id:
        flash("Enter a valid UPI ID (for example, name@bank) or leave it blank.")
        return redirect(url_for("index"))

    try:
        employee = Employee(
            name=request.form["name"].strip(),
            email=request.form["email"].strip(),
            hourly_rate=float(request.form["hourly_rate"]),
            tax_rate=float(request.form.get("tax_rate", 0.15)),
            upi_id=upi_id,
        )
        if not employee.name or employee.hourly_rate < 0 or not 0 <= employee.tax_rate <= 1:
            raise ValueError
    except (KeyError, ValueError):
        flash("Enter a name, valid email, non-negative hourly rate, and tax rate from 0 to 1.")
        return redirect(url_for("index"))

    db.session.add(employee)
    db.session.commit()
    flash("Employee added.")
    return redirect(url_for("index"))


@app.route("/process-payroll", methods=["POST"])
def process_payroll():
    try:
        employee_id = int(request.form["employee_id"])
        hours_worked = float(request.form["hours_worked"])
    except (KeyError, ValueError):
        flash("Select an employee and enter valid hours worked.")
        return redirect(url_for("index"))

    employee = db.session.get(Employee, employee_id)
    if not employee or hours_worked < 0:
        flash("Select an existing employee and enter non-negative hours worked.")
        return redirect(url_for("index"))

    pay_data = calculate_paycheck(employee.hourly_rate, hours_worked, employee.tax_rate)
    payroll_record = Payroll(
        employee_id=employee.id,
        hours_worked=hours_worked,
        gross_pay=pay_data["gross_pay"],
        tax_deductions=pay_data["tax_deductions"],
        net_pay=pay_data["net_pay"],
        status="PROCESSED",
    )
    db.session.add(payroll_record)
    db.session.commit()
    flash(f"Paycheck #{payroll_record.id} processed.")
    return redirect(url_for("index"))


@app.route("/payroll/<int:payroll_id>/qr.png")
def payroll_qr(payroll_id):
    payroll_record = db.session.get(Payroll, payroll_id)
    if not payroll_record:
        abort(404)

    employee = payroll_record.employee
    if not employee.upi_id or "@" not in employee.upi_id:
        abort(404, description="A valid employee UPI ID is required to generate this QR code.")

    payment_uri = "upi://pay?" + urlencode({
        "pa": employee.upi_id,
        "pn": employee.name,
        "am": f"{payroll_record.net_pay:.2f}",
        "cu": "INR",
        "tn": f"Paycheck {payroll_record.id}",
    })
    image = qrcode.make(payment_uri)
    output = BytesIO()
    image.save(output, format="PNG")
    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "image/png"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/payroll/<int:payroll_id>/payslip.pdf")
def payroll_payslip(payroll_id):
    payroll_record = db.session.get(Payroll, payroll_id)
    if not payroll_record:
        abort(404)

    employee = payroll_record.employee
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=letter,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    styles = getSampleStyleSheet()
    content = [
        Paragraph("PayFlow Payslip", styles["Title"]),
        Spacer(1, 0.2 * inch),
        Paragraph(f"Paycheck #{payroll_record.id}", styles["Heading2"]),
        Paragraph(f"Employee: {escape(employee.name)}", styles["Normal"]),
        Paragraph(f"Email: {escape(employee.email)}", styles["Normal"]),
        Paragraph(
            f"Processed: {payroll_record.processed_at.strftime('%Y-%m-%d %H:%M UTC')}",
            styles["Normal"],
        ),
        Spacer(1, 0.2 * inch),
    ]
    pay_table = Table([
        ["Pay detail", "Amount (INR)"],
        ["Hours worked", f"{payroll_record.hours_worked:.2f}"],
        ["Gross pay", f"{payroll_record.gross_pay:.2f}"],
        ["Tax deductions", f"-{payroll_record.tax_deductions:.2f}"],
        ["Net pay", f"{payroll_record.net_pay:.2f}"],
        ["Status", payroll_record.status],
    ], colWidths=[3.5 * inch, 2 * inch])
    pay_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#007bff")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
        ("ALIGN", (1, 1), (1, -1), "RIGHT"),
        ("BACKGROUND", (0, -2), (-1, -2), colors.HexColor("#f1f5f9")),
        ("FONTNAME", (0, -2), (-1, -1), "Helvetica-Bold"),
        ("PADDING", (0, 0), (-1, -1), 8),
    ]))
    content.extend([pay_table, Spacer(1, 0.25 * inch)])

    if employee.upi_id and "@" in employee.upi_id:
        payment_uri = "upi://pay?" + urlencode({
            "pa": employee.upi_id,
            "pn": employee.name,
            "am": f"{payroll_record.net_pay:.2f}",
            "cu": "INR",
            "tn": f"Paycheck {payroll_record.id}",
        })
        qr_image = qrcode.make(payment_uri)
        qr_output = BytesIO()
        qr_image.save(qr_output, format="PNG")
        qr_output.seek(0)
        content.extend([
            Paragraph("UPI payment QR", styles["Heading3"]),
            Image(qr_output, width=1.5 * inch, height=1.5 * inch),
        ])

    document.build(content)
    output.seek(0)
    return send_file(
        output,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"payslip-{payroll_record.id}.pdf",
    )


# --- JSON API ENDPOINTS FOR SCALABILITY & HIGH LOAD ---

@app.route("/api/employees", methods=["GET", "POST"])
def api_employees():
    if request.method == "POST":
        data = request.get_json() or {}
        new_emp = Employee(
            name=data.get("name", "Test User"),
            email=data.get("email", f"user_{db.session.query(Employee).count()}@payflow.com"),
            hourly_rate=float(data.get("hourly_rate", 30.0)),
            tax_rate=float(data.get("tax_rate", 0.15)),
            upi_id=(data.get("upi_id") or "").strip() or None,
        )
        db.session.add(new_emp)
        db.session.commit()
        return jsonify({"message": "Employee created", "id": new_emp.id}), 201
    
    employees = Employee.query.all()
    return jsonify([
        {"id": e.id, "name": e.name, "rate": e.hourly_rate, "upi_id": e.upi_id}
        for e in employees
    ]), 200


@app.route("/api/process-payroll", methods=["POST"])
def api_process_payroll():
    """Processes a single paycheck via API request"""
    data = request.get_json() or {}
    employee_id = data.get("employee_id", 1)
    hours_worked = float(data.get("hours_worked", 40.0))

    employee = Employee.query.get(employee_id)
    if not employee:
        # Auto-create fallback employee if database is fresh during load tests
        employee = Employee(name="Default Load User", email="loadtest@payflow.com", hourly_rate=25.0, tax_rate=0.15)
        db.session.add(employee)
        db.session.commit()

    pay_data = calculate_paycheck(employee.hourly_rate, hours_worked, employee.tax_rate)

    payroll_record = Payroll(
        employee_id=employee.id,
        hours_worked=hours_worked,
        gross_pay=pay_data["gross_pay"],
        tax_deductions=pay_data["tax_deductions"],
        net_pay=pay_data["net_pay"],
        status="PROCESSED"
    )

    db.session.add(payroll_record)
    db.session.commit()

    return jsonify({
        "status": "SUCCESS",
        "payroll_id": payroll_record.id,
        "net_pay": pay_data["net_pay"],
        "qr_url": (
            url_for("payroll_qr", payroll_id=payroll_record.id)
            if employee.upi_id else None
        ),
        "payslip_url": url_for("payroll_payslip", payroll_id=payroll_record.id),
    }), 200

if __name__ == "__main__":
    # Use threaded execution to handle multiple incoming requests simultaneously
    app.run(debug=True, threaded=True)