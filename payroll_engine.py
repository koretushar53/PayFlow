def calculate_paycheck(hourly_rate, hours_worked, tax_rate):
    # Standard 40 hours limit; 1.5x overtime rate
    if hours_worked > 40:
        regular_hours = 40
        overtime_hours = hours_worked - 40
    else:
        regular_hours = hours_worked
        overtime_hours = 0

    gross_pay = (regular_hours * hourly_rate) + (overtime_hours * hourly_rate * 1.5)
    tax_deductions = gross_pay * tax_rate
    net_pay = gross_pay - tax_deductions

    return {
        "gross_pay": round(gross_pay, 2),
        "tax_deductions": round(tax_deductions, 2),
        "net_pay": round(net_pay, 2)
    }