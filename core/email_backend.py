import ssl
import smtplib
from django.core.mail.backends.smtp import EmailBackend


class NoVerifyEmailBackend(EmailBackend):
    def open(self):
        if self.connection:
            return False
        ctx = ssl._create_unverified_context()
        self.connection = smtplib.SMTP_SSL(self.host, self.port, context=ctx)
        self.connection.login(self.username, self.password)
        return True
