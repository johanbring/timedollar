import tkinter as tk
from tkinter import messagebox
import smtplib
import imaplib
import sqlite3
import json
from email.mime.text import MIMEText
from email.parser import BytesParser
from email.policy import default
from datetime import datetime
import os
import time
import hashlib
import uuid


# Database setup
conn = sqlite3.connect('ledger.db')
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS ledger (
        id INTEGER PRIMARY KEY,
        receiver_email TEXT,
        amount REAL,
        message TEXT,
        date TEXT,
        email_subject TEXT UNIQUE,
        transaction_hash TEXT UNIQUE,
        transaction_uuid TEXT UNIQUE
    )
''')
conn.commit()

# Load settings from a JSON file
SETTINGS_FILE = "settings.json"

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as file:
            return json.load(file)
    return {"email": "", "password": "", "smtp_server": "", "imap_server": ""}

def save_settings(email, password, smtp, imap):
    settings = {"email": email, "password": password, "smtp_server": smtp, "imap_server": imap}
    with open(SETTINGS_FILE, "w") as file:
        json.dump(settings, file)

# Load saved settings
settings = load_settings()
EMAIL_ADDRESS = settings["email"]
EMAIL_PASSWORD = settings["password"]
SMTP_SERVER = settings["smtp_server"]
IMAP_SERVER = settings["imap_server"]
SMTP_PORT = 587
IMAP_PORT = 993


# Function to open settings window
def open_settings():
    settings_window = tk.Toplevel(root)
    settings_window.title("Settings")

    tk.Label(settings_window, text="Email Address:").pack()
    email_entry = tk.Entry(settings_window)
    email_entry.pack()
    email_entry.insert(0, settings["email"])

    tk.Label(settings_window, text="Password:").pack()
    password_entry = tk.Entry(settings_window, show="*")
    password_entry.pack()
    password_entry.insert(0, settings["password"])

    tk.Label(settings_window, text="SMTP Server:").pack()
    smtp_entry = tk.Entry(settings_window)
    smtp_entry.pack()
    smtp_entry.insert(0, settings["smtp_server"])

    tk.Label(settings_window, text="IMAP Server:").pack()
    imap_entry = tk.Entry(settings_window)
    imap_entry.pack()
    imap_entry.insert(0, settings["imap_server"])

    def save_and_close():
        global EMAIL_ADDRESS, EMAIL_PASSWORD, SMTP_SERVER, IMAP_SERVER
        EMAIL_ADDRESS = email_entry.get()
        EMAIL_PASSWORD = password_entry.get()
        SMTP_SERVER = smtp_entry.get()
        IMAP_SERVER = imap_entry.get()
        save_settings(EMAIL_ADDRESS, EMAIL_PASSWORD, SMTP_SERVER, IMAP_SERVER)
        messagebox.showinfo("Settings", "Settings saved successfully.")
        settings_window.destroy()

    save_button = tk.Button(settings_window, text="Save", command=save_and_close)
    save_button.pack()


def generate_transaction_uuid():
    """Generate a unique UUID for each transaction."""
    return str(uuid.uuid4())

# Function to send email
def send_email(to_email, amount, message, transaction_uuid, retries=3):
    """Send email and return True if successful, False otherwise."""
    subject = f"Transaction - {amount} - {message} - UUID: {transaction_uuid}"
    msg = MIMEText(f"{message}\n\nTransaction UUID: {transaction_uuid}")
    msg['Subject'] = subject
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = to_email

    attempt = 0
    while attempt < retries:
        try:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10) as server:
                server.starttls()
                server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
                server.sendmail(EMAIL_ADDRESS, to_email, msg.as_string())
            print(f"✅ Email sent successfully to {to_email}")
            return True  # Return success
        except smtplib.SMTPAuthenticationError:
            print("❌ SMTP Authentication Error: Check your email and password.")
            return False
        except smtplib.SMTPConnectError:
            print(f"⚠️ Connection Error: Could not connect to {SMTP_SERVER}. Retrying...")
        except smtplib.SMTPException as e:
            print(f"❌ SMTP Error: {e}")
        except Exception as e:
            print(f"❌ Unexpected Error: {e}")

        attempt += 1
        time.sleep(2)  # Wait before retrying

    print("❌ Failed to send email after multiple attempts.")
    return False  # Return failure



def generate_transaction_hash(amount, receiver_email, message):
    """Generate a unique hash for the transaction."""
    transaction_data = f"{amount}{receiver_email}{message}"
    return hashlib.sha256(transaction_data.encode()).hexdigest()  # SHA-256 for uniqueness

def fetch_emails():
    try:
        with imaplib.IMAP4_SSL(IMAP_SERVER) as mail:
            mail.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            mail.select('inbox')
            result, data = mail.search(None, 'ALL')

            if result == 'OK':
                for num in data[0].split():
                    result, msg_data = mail.fetch(num, '(RFC822)')
                    if result == 'OK':
                        try:
                            msg = BytesParser(policy=default).parsebytes(msg_data[0][1])
                            subject = msg['Subject']
                            sender = msg['From']
                            sender_email = sender.split('<')[-1].split('>')[0]  # Extract email address

                            # Skip emails with no subject
                            if not subject:
                                print(f"⚠️ Skipping email with missing subject from {sender}")
                                continue

                            # Ensure the subject contains "Transaction"
                            if "Transaction" not in subject:
                                print(f"⚠️ Skipping unrelated email: {subject}")
                                continue

                            details = subject.split(" - ")

                            # Ensure there are at least 3 parts (Transaction - Amount - Message - UUID)
                            if len(details) < 4:
                                print(f"⚠️ Invalid transaction format: {subject}")
                                continue

                            try:
                                amount = float(details[1])  # Ensure amount is a valid number
                                transaction_message = details[2]
                                transaction_uuid = details[3].replace("UUID:", "").strip()
                            except ValueError:
                                print(f"⚠️ Invalid amount format in email: {subject}")
                                continue

                            receiver_email = sender_email
                            date_received = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                            # Check if the UUID already exists in the database
                            cursor.execute("SELECT * FROM ledger WHERE transaction_uuid = ?", (transaction_uuid,))
                            existing_transaction = cursor.fetchone()

                            if existing_transaction is None:
                                cursor.execute(
                                    "INSERT INTO ledger (receiver_email, amount, message, date, email_subject, transaction_hash, transaction_uuid) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                    (receiver_email, amount, transaction_message, date_received, subject, generate_transaction_hash(amount, receiver_email, transaction_message), transaction_uuid)
                                )
                                conn.commit()

                                # Send confirmation email back to sender
                                send_email(sender_email, amount, "Your payment has been received successfully.", transaction_uuid)
                            else:
                                print(f"⚠️ Duplicate UUID detected: {transaction_uuid}")
                        except Exception as e:
                            print(f"❌ Error processing email: {e}")
    except Exception as e:
        print(f"❌ Error fetching emails: {e}")



# Function to show ledger
def show_ledger():
    ledger_window = tk.Toplevel(root)
    ledger_window.title("Ledger")

    cursor.execute("SELECT SUM(amount) FROM ledger")
    total_value = cursor.fetchone()[0]
    total_value = total_value if total_value is not None else 0.0

    total_label = tk.Label(ledger_window, text=f"Total Ledger Value: ${total_value:.2f}")
    total_label.pack()

    cursor.execute("SELECT * FROM ledger")
    transactions = cursor.fetchall()

    text = tk.Text(ledger_window)
    text.pack()

    for transaction in transactions:
        text.insert(tk.END, f"ID: {transaction[0]}, Receiver: {transaction[1]}, Amount: {transaction[2]}, Message: {transaction[3]}, Date: {transaction[4]}\n")

# Function to add a new transaction
def add_transaction():
    receiver_email = receiver_email_entry.get()
    amount_text = amount_entry.get()
    message = message_entry.get()

    if not receiver_email or not amount_text or not message:
        messagebox.showerror("Error", "Please fill in all fields.")
        return

    try:
        amount = float(amount_text)  # Convert amount to float
    except ValueError:
        messagebox.showerror("Error", "Invalid amount. Please enter a valid number.")
        return

    # Generate a new UUID for the transaction
    transaction_uuid = generate_transaction_uuid()

    # Generate a unique hash for the transaction
    transaction_hash = generate_transaction_hash(amount, receiver_email, message)

    # Check if the UUID already exists
    cursor.execute("SELECT * FROM ledger WHERE transaction_uuid = ?", (transaction_uuid,))
    existing_transaction = cursor.fetchone()

    if existing_transaction:
        messagebox.showerror("Error", "This transaction has already been recorded.")
        return

    # Show confirmation popup
    confirmation = messagebox.askyesno(
        "Confirm Transaction",
        f"Send {amount:.2f} to {receiver_email}?\n\nMessage: {message}"
    )

    if confirmation:  # Only proceed if user clicks "Yes"
        date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        email_sent = send_email(receiver_email, amount, message, transaction_uuid)

        if email_sent:
            cursor.execute(
                "INSERT INTO ledger (receiver_email, amount, message, date, transaction_hash, transaction_uuid) VALUES (?, ?, ?, ?, ?, ?)",
                (receiver_email, -amount, message, date, transaction_hash, transaction_uuid)
            )
            conn.commit()
            messagebox.showinfo("Success", "Transaction added and email sent.")
        else:
            messagebox.showerror("Error", "Transaction failed. Email could not be sent.")
    else:
        messagebox.showinfo("Cancelled", "Transaction was cancelled.")

# Function to refresh the ledger
def refresh_ledger():
    fetch_emails()
    messagebox.showinfo("Refresh", "Ledger refreshed from inbox.")

# Tkinter GUI setup
root = tk.Tk()
root.title("Transaction Ledger")

# Transaction input fields
tk.Label(root, text="Receiver Email:").pack()
receiver_email_entry = tk.Entry(root)
receiver_email_entry.pack()

tk.Label(root, text="Amount:").pack()
amount_entry = tk.Entry(root)
amount_entry.pack()

tk.Label(root, text="Message:").pack()
message_entry = tk.Entry(root)
message_entry.pack()

# Buttons
send_button = tk.Button(root, text="Send Transaction", command=add_transaction)
send_button.pack()

refresh_button = tk.Button(root, text="Refresh Ledger", command=refresh_ledger)
refresh_button.pack()

show_button = tk.Button(root, text="Show Ledger", command=show_ledger)
show_button.pack()

settings_button = tk.Button(root, text="Settings", command=open_settings)
settings_button.pack()

# Start Tkinter main loop
root.mainloop()
