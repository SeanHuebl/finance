import os

from cs50 import SQL
import time
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# Create a new table called 'transaction_history' if one doesnt exist
db.execute("CREATE TABLE IF NOT EXISTS transaction_history (\
    transaction_id INTEGER PRIMARY KEY AUTOINCREMENT UNIQUE NOT NULL, account_id INTEGER NOT NULL, company_name TEXT NOT NULL, ticker_symbol TEXT NOT NULL, amount INTEGER NOT NULL,\
    price REAL NOT NULL, transaction_type TEXT NOT NULL, date_time INTEGER NOT NULL, FOREIGN KEY (account_id) REFERENCES users (id))")

# Create a new table called 'portfolio' if one doesnt exist
db.execute("CREATE TABLE IF NOT EXISTS portfolio (\
    entry_id INTEGER PRIMARY KEY AUTOINCREMENT UNIQUE NOT NULL, account_id INTEGER NOT NULL,\
    company_name TEXT NOT NULL, symbol TEXT NOT NULL, shares INTEGER NOT NULL,\
    stock_price INTEGER NOT NULL, total_value INTEGER NOT NULL, FOREIGN KEY (account_id) REFERENCES USERS (id))")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""

    # Query the portfolio table for the specific user and assign variable so it can be passed to jinja
    user_portfolio = db.execute("SELECT * FROM portfolio WHERE account_id = ? ORDER BY symbol", session["user_id"])

    # Grab user's cash balance
    user_cash = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])[0]["cash"]

    user_value = 0.0

    for entry in user_portfolio:
        # Access API to grab current stock price for each entry
        stock_price = lookup(entry["symbol"])["price"]

        # Update portfolio
        db.execute("UPDATE portfolio SET stock_price = ?, total_value = ? WHERE account_id = ? AND symbol = ?",
            stock_price,
            stock_price * entry["shares"],
            session["user_id"],
            entry["symbol"])

        user_value += entry["total_value"]

    # Grab updated portfolio
    user_portfolio = db.execute("SELECT * FROM portfolio WHERE account_id = ? ORDER BY symbol", session["user_id"])

    # Render homepage and pass variables to jinja
    return render_template("index.html", user_portfolio = user_portfolio, user_cash = user_cash, user_value = user_value + user_cash)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # If symbol field is blank return error page
        if not request.form.get("symbol"):
            return apology("Ticker symbol cannot be blank!")

        # Assign variable symbol field val
        symbol = request.form.get("symbol")

        # If shares field is blank return error page
        if not request.form.get("shares"):
            return apology("Number of shares cannot be blank!")

        # Try to convert shares field input to int, if a number wasnt input return error page
        try:
            shares = int(request.form.get("shares"))

        except ValueError:
            return apology("Shares must be a whole number!")

        # If shares field input is 0 or negative return error page
        if shares < 1:
            return apology("You must purchase 1 or more shares!")

        # If API lookup of the symbol field returns None return error page
        if lookup(symbol) == None:
            return apology("Ticker symbol not found!")

        # Once checks are passed assign variables

        # Assign API lookup of symbol input to variable
        symbol_data = lookup(symbol)

        # Assign symbol data price to variable
        symbol_price = symbol_data["price"]

        # Assign total purchase cost of price * shares to variable
        purchase_cost = symbol_price * shares

        # Query 'users' table to check balance of user. session["user_id"] refers to person logged in
        user_balance = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])[0]["cash"]

        # If user has less money in their account than cost of shares return an error
        if purchase_cost > user_balance:
            return apology("Balance too low to complete transaction!")

        # Once all checks pass update the user's cash amount to reflect the purchase

        # Update the user's transaction history
        db.execute("INSERT INTO transaction_history (account_id, company_name, ticker_symbol, amount, price, transaction_type, date_time) VALUES(?, ?, ?, ?, ?, ?, ?)",
            session["user_id"],
            symbol_data["name"],
            symbol_data["symbol"],
            shares,
            symbol_price,
            "Buy",
            time.strftime("%m/%d/%y %I:%M %p GMT"))

        # Check if the user already owns shares of the company if they don't insert into their portfolio how many shares they have after purchase and return bought page

        if len(db.execute("SELECT shares FROM portfolio WHERE symbol = ? AND account_id = ?", symbol_data["symbol"], session["user_id"])) == 0:

            db.execute("INSERT INTO portfolio (account_id, company_name, symbol, shares, stock_price, total_value) VALUES(?, ?, ?, ?, ?, ?)",
            session["user_id"],
            symbol_data["name"],
            symbol_data["symbol"],
            shares,
            symbol_price,
            shares * symbol_price)

            # Update user balance after all is said and done
            db.execute("UPDATE users SET cash = ? FROM users AS u WHERE u.id = ?", user_balance - purchase_cost, session["user_id"])

            flash("Purchase Complete")
            return redirect("/")

        # Otherwise, update their portfolio with increasing the shares they bought of company and return bought page
        db.execute("UPDATE portfolio SET shares = ? WHERE account_id = ? AND symbol = ?",
            db.execute("SELECT shares FROM portfolio WHERE account_id = ? AND symbol = ?",
                session["user_id"],
                symbol_data["symbol"])[0]["shares"]
            + shares,
            session["user_id"],
            symbol_data["symbol"])

        # Update user balance after all is said and done
        db.execute("UPDATE users SET cash = ? FROM users AS u WHERE u.id = ?", user_balance - purchase_cost, session["user_id"])

        flash("Purchase Complete")
        return redirect("/")

    return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""

    # Execute query on transaction table based on user order by date / time
    transaction_history = db.execute("SELECT * FROM transaction_history WHERE account_id = ? ORDER BY transaction_id DESC", session["user_id"])

    # Render history.html page and pass in the query table so jinja can access it
    return render_template("history.html", transaction_history = transaction_history)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = ?", request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        flash("Logged In")
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    flash("Successfully Logged Out")
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # If symbol field is blank return error page
        if not request.form.get("symbol"):
            return apology("Ticker symbol cannot be blank!")

        # Assign symbol input to variable
        symbol = request.form.get("symbol")

        # If API lookup of symbol returns None return error page
        if lookup(symbol) == None:
            return apology("Ticker symbol not found!")

        # Once those checks clear, assign variable to data returned by API lookup of symbol
        symbol_data = lookup(symbol)

        # Return quoted page passing in symbol_data variable for jinja access
        return render_template("quoted.html", symbol_data=symbol_data)

    return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # If username field is blank return error page
        if not request.form.get("username"):
            return apology("Username cannot be blank!")

        # If password field is blank return error page
        if not request.form.get("password"):
            return apology("Password cannot be blank!")

        # If password and confirm password fields do not match return error page
        if request.form.get("password") != request.form.get("confirmation"):
            return apology("Passwords do not match!")

        # Loop over every char in password to see if it contains a number, digit, and special char

        # Set variables for numeric, alpha, and special
        contains_letter = False
        contains_number = False
        contains_symbol = False

        for x in request.form.get("password"):

            # If char is alphabetical change variable to true since password will have at least 1 letter
            if x.isalpha() and contains_letter == False:
                contains_letter = True

            # If char is a digit change variable to true since password will have at least 1 number
            if x.isdigit() and contains_number == False:
                contains_number = True

            # If char is not a digit or part of the alphabet change variable to true since passworld will have at least 1 symbol
            if not x.isalnum() and contains_symbol == False:
                contains_symbol = True

        # Check if all 3 password variables are true
        if not contains_letter or not contains_number or not contains_symbol:
            return apology("Password must contain at least 1 letter, 1 digit, and 1 symbol!")

        # If username already exists
        if len(db.execute("SELECT * FROM users WHERE username = ?", request.form.get("username"))) != 0:
            return apology("Username already taken, please choose another one!")


        # Temp variables for username and password
        username = request.form.get("username")

        # Instead of storing the actual password we will store the hash of the password for security
        password = generate_password_hash(request.form.get("password"), method="sha256", salt_length=8)

        #Insert into 'users' table new user, all new users get 10,000 cash as bonus for signing up
        db.execute("INSERT INTO users (username, hash, cash) VALUES(?, ?, ?)", username, password, 10000.00)

        # Users will be redirected to homepage and prompted to log in
        return redirect("/")

    return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""

    # Grab user portfolio to pass into jinja
    user_stocks = db.execute("SELECT symbol FROM portfolio WHERE account_id = ? ORDER BY symbol", session["user_id"])

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # If symbol field is blank return error page
        if not request.form.get("symbol"):
            return apology("Ticker symbol cannot be blank!")

        # Assign symbol input to variable
        symbol = request.form.get("symbol")

        # If shares field is blank return error page
        if not request.form.get("shares"):
            return apology("Number of shares cannot be blank!")

        # Try to convert number of shares input to int, if it fails return error page
        try:
            shares_sold = int(request.form.get("shares"))

        except ValueError:
            return apology("Shares must be a number!")

        # If input to shares field is less than 1 return error page
        if shares_sold < 1:
            return apology("You must sell 1 or more shares!")

        # If API lookup of symbol input is None, return error page
        if lookup(symbol) == None:
            return apology("Ticker symbol not found!")

        # Assign API lookup of symbol data to variable
        symbol_data = lookup(symbol)

        # Assign price of share to variable
        symbol_price = symbol_data["price"]

        # Lookup the user's balance from the  'users' table
        user_balance = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])[0]["cash"]

        # Find total shares of company that the user owns from 'portfolio' table
        num_shares = db.execute("SELECT shares FROM portfolio WHERE account_id = ? AND symbol = ?",
                        session["user_id"],
                        symbol_data["symbol"])

        # Error if somehow they try to sell shares they don't own
        if len(num_shares) != 1:
            return apology("An error occured, please try again later")

        # If user is trying to sell more shares than they own return error page
        if shares_sold > num_shares[0]["shares"]:
            return apology("You can't sell more shares than you own!")

        # Update user balance variable with price of shares sold
        user_balance += symbol_price * shares_sold

        # Insert the sell transaction into the 'transaction' table
        db.execute("INSERT INTO transaction_history (account_id, company_name, ticker_symbol, amount, price, transaction_type, date_time) VALUES(?, ?, ?, ?, ?, ?, ?)",
            session["user_id"],
            symbol_data["name"],
            symbol_data["symbol"],
            shares_sold,
            symbol_price,
            "Sell",
            time.strftime("%m/%d/%y %I:%M %p GMT"))

        # If user sells all their shares of company, delete row from their 'portfolio' table containing their shares of said company
        if shares_sold == num_shares[0]["shares"]:
            db.execute("DELETE FROM portfolio WHERE account_id = ? AND symbol = ?",
            session["user_id"],
            symbol_data["symbol"])

            # Update user balance in table
            db.execute("UPDATE users SET cash = ? FROM users AS u WHERE u.id = ?", user_balance, session["user_id"])

            flash("Sale Complete")
            return redirect("/")

        # Otherwise update their portfolio with new amount of shares that they own
        db.execute("UPDATE portfolio SET shares = ? WHERE account_id = ? AND symbol = ?",
            db.execute("SELECT shares FROM portfolio WHERE account_id = ? AND symbol = ?",
                session["user_id"],
                symbol_data["symbol"])[0]["shares"]
            - shares_sold,
            session["user_id"],
            symbol_data["symbol"])

        # Update user balance in table
        db.execute("UPDATE users SET cash = ? FROM users AS u WHERE u.id = ?", user_balance, session["user_id"])

        # Update portfolio total value

        flash("Sale Complete")
        return redirect("/")

    return render_template("sell.html", user_stocks = user_stocks)
