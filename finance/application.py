import os

from cs50 import SQL
from flask import Flask, flash, jsonify, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/")
@login_required
def index():

    # Load user's portfolio
    list = db.execute("SELECT * FROM portfolio WHERE id = :id", id=session["user_id"])

    # Update portfolio information for current prices
    total = 0
    holdings = []
    for x in list:
        stock = lookup(x["symbol"])
        symbol = stock["symbol"]
        name = stock["name"]
        shares = x["shares"]
        price = stock["price"]
        value = price * shares
        holdings.append({"symbol": symbol, "name": name, "shares": shares, "price": usd(price), "value": usd(value)})
        total = total + stock["price"] * x["shares"]

    # Fetch current cash and add to portfolio total
    money = db.execute("SELECT cash FROM users WHERE id = :id", id=session["user_id"])
    cash = float(money[0]["cash"])
    total = total + cash

    return render_template("index.html", holdings=holdings, total=usd(total), cash=usd(cash))


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":
        stock = lookup(request.form.get("symbol"))

        # Check to make sure the ticker exists
        if not stock:
            return apology("Not a valid ticker", 400)

        # Make sure shares are positive integer
        try:
            shares = int(request.form.get("shares"))
        except ValueError:
            return apology("Shares must be an integer", 400)
        if shares <= 0:
            return apology("Shares must be a positive integer", 400)

        # See if user can afford the purchase
        cash = db.execute("SELECT cash FROM users WHERE id = :id", id=session["user_id"])
        spend = int(request.form.get("shares")) * stock["price"]
        if spend > float(cash[0]["cash"]):
            return apology("You do not have enough money", 400)

        # Add purchase into transaction database
        db.execute("INSERT INTO transactions(id, type, symbol, shares, price) VALUES(:id, 'Purchase', :symbol, :shares, :price)",
                   id=session["user_id"], symbol=stock["symbol"], shares=request.form.get("shares"), price=usd(stock["price"]))

        # Adjust user cash balance
        db.execute("UPDATE users SET cash = cash - :spend WHERE id = :id", spend=spend, id=session["user_id"])

        # Retrieve current share count from portfolio
        holding = db.execute("SELECT shares FROM portfolio WHERE id = :id AND symbol = :symbol",
                             id=session["user_id"], symbol=stock["symbol"])

        # If no shares, add the symbol to the portfolio table
        if not holding:
            db.execute("INSERT INTO portfolio(id, symbol, name, shares) VALUES(:id, :symbol, :name, :shares)",
                       id=session["user_id"], symbol=stock["symbol"], name=stock["name"], shares=request.form.get("shares"))

        # Otherwise, increment the share count by the purchase
        else:
            db.execute("UPDATE portfolio SET shares = shares + :shares WHERE id = :id AND symbol = :symbol",
                       shares=int(request.form.get("shares")), id=session["user_id"], symbol=stock["symbol"])

        # Redirect user to index table
        return redirect("/")

    else:
        return render_template("buy.html")


@app.route("/check", methods=["GET"])
def check():
    username = str(request.args.get("username"))

    # Check if username taken
    if len(username) == 0 or len(db.execute("SELECT * FROM users WHERE username = :username", username=username)) != 0:
        return jsonify(False)

    # Otherwise send back true
    else:
        return jsonify(True)


@app.route("/history")
@login_required
def history():

    # Load user's transaction history
    transactions = db.execute("SELECT * FROM transactions WHERE id = :id", id=session["user_id"])
    return render_template("history.html", transactions=transactions)


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
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
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
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":
        stock = lookup(request.form.get("symbol"))

        # Check to make sure the ticker exists
        if not stock:
            return apology("Not a valid ticker", 400)

        # Reformat the price into USD format
        stock["price"] = usd(stock["price"])

        return render_template("quoted.html", stock=stock)

    else:
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    # Forget any user_id
    session.clear()

    # User reached route via GET (as by submitting a form via GET)
    if request.method == "GET":
        return render_template("register.html")

    # User reached route via POST (as by submitting a form via POST)
    else:

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 400)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 400)

        # Ensure password confirmation was submitted
        elif not request.form.get("confirmation"):
            return apology("must confirm password", 400)

        # Ensure passwords match
        if request.form.get("password") != request.form.get("confirmation"):
            return apology("passwords do not match", 400)

        # Encrypt password
        hash = generate_password_hash(request.form.get("password"))

        # Ensure username is unique
        rows = db.execute("SELECT * FROM users WHERE username = :username", username=request.form.get("username"))
        if len(rows) != 0:
            return apology("username already taken", 400)

        # Input username into databse
        rows = db.execute("INSERT INTO users (username, hash) VALUES(:username, :hash)",
                          username=request.form.get("username"), hash=hash)

        # Remember which user has logged in
        rows = db.execute("SELECT * FROM users WHERE username = :username", username=request.form.get("username"))
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():

    # Retrieve the list of stocks and number of shares user has
    list = db.execute("SELECT shares, symbol FROM portfolio WHERE id = :id", id=session["user_id"])

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure ticker was selected
        if not request.form.get("symbol"):
            return apology("must provide symbol to sell", 400)

        # Ensure share count was submitted
        elif not request.form.get("shares"):
            return apology("must provide shares to sell", 400)

        # Retrieve share count of selected ticker
        holding = db.execute("SELECT shares FROM portfolio WHERE id = :id AND symbol = :symbol",
                             id=session["user_id"], symbol=request.form.get("symbol"))

        # See if user has enough shares to sell
        if int(request.form.get("shares")) > int(holding[0]["shares"]):
            return apology("You do not have enough shares to sell", 400)

        # If so, retrieve pricing information for the stock
        stock = lookup(request.form.get("symbol"))

        # Add sale into transaction database
        db.execute("INSERT INTO transactions(id, type, symbol, shares, price) VALUES(:id, 'Sale', :symbol, :shares, :price)",
                   id=session["user_id"], symbol=stock["symbol"], shares=-int(request.form.get("shares")), price=usd(stock["price"]))

        # Adjust user cash balance
        spend = -int(request.form.get("shares")) * stock["price"]
        db.execute("UPDATE users SET cash = cash - :spend WHERE id = :id", spend=spend, id=session["user_id"])

        # Remove the sold shares from the holdings
        db.execute("UPDATE portfolio SET shares = shares + :shares WHERE id = :id AND symbol = :symbol",
                   shares=-int(request.form.get("shares")), id=session["user_id"], symbol=stock["symbol"])

        # If holdings are currently zero, remove the holding from user's portfolio
        db.execute("DELETE FROM portfolio WHERE id = :id AND shares = 0", id=session["user_id"])

        # Redirect user to index table
        return redirect("/")

    else:
        return render_template("sell.html", list=list)


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
