from locust import HttpUser, task, between
import random

class PayFlowUser(HttpUser):
    # Wait between 0.1 to 0.5 seconds between tasks to simulate high traffic volume
    wait_time = between(0.1, 0.5)

    @task(3)
    def process_payroll_request(self):
        """Simulate processing a paycheck payment calculation"""
        payload = {
            "employee_id": 1,
            "hours_worked": random.choice([35.0, 40.0, 45.0, 50.0])
        }
        self.client.post("/api/process-payroll", json=payload)

    @task(1)
    def view_dashboard(self):
        """Simulate viewing the dashboard endpoint"""
        self.client.get("/")