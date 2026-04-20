import threading
from django.core.mail import EmailMessage

class EmailThread(threading.Thread):
    def __init__(self, email):
        self.email = email
        threading.Thread.__init__(self)

    def run(self):
        # This sends the email in a separate thread (background)
        # so the user doesn't wait.
        self.email.send()

def send_html_email(subject, body, to_email):
    email = EmailMessage(
        subject=subject,
        body=body,
        to=[to_email]
    )
    # Start the background process
    EmailThread(email).start()