import os

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime

from helpers import apology, login_required, lookup, usd

# Ensure environment variable is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")

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
basedir = os.path.abspath(os.path.dirname(__file__))
db = SQL('sqlite:///' + os.path.join(basedir, 'finance.db'))


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""

    # get the stocks and the shares of each stock that the user owns from the database
    portfolio = db.execute("SELECT company, shares FROM portfolio WHERE id = :id",
                           id=session["user_id"])

    # variable to hold the total worth of all the stock options
    total_value = 0

    # iterate through all the stocks to calculate the total worth of their value
    for stocks in portfolio:
        symbol = stocks["company"]
        shares = stocks["shares"]
        try:  # free API key is rate limited
            stock = lookup(symbol)
            value = stock["price"] * shares
        except:
            return apology("too many API requests, slow down")
        total_value += value
        db.execute("UPDATE portfolio SET price=:price, total=:total WHERE id=:id AND company=:company",
                   price=usd(stock["price"]), total=usd(value),
                   id=session["user_id"], company=stock["symbol"])

    # get user's cash
    cash = db.execute("SELECT cash FROM users WHERE id = :id", id=session["user_id"])
    cash = cash[0]["cash"]

    net_worth = total_value + cash

    # print updated portfolio to index page
    updated_portfolio = db.execute("SELECT * FROM portfolio WHERE id = :id", id=session["user_id"])

    return render_template("index.html", stocks=updated_portfolio, total=usd(net_worth), cash=usd(cash))


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""

    if request.method == "POST":
        stock = lookup(request.form.get("symbol"))
        if not stock:
            return apology("stock is not valid", 400)

        try:
            shares = int(request.form.get("shares"))
            if shares < 0:
                return apology("no negative stocks", 400)
        except:
            return apology("must provide number of shares!")

        price = float(stock["price"]) * shares
        money = db.execute("SELECT cash FROM users WHERE id = :id", id=session["user_id"])
        money = float(money[0]["cash"])

        if price > money:
            return apology("you're not that rich")

        # add transaction to history database
        db.execute("INSERT INTO history (id, company, shares, price, date) "
                   "VALUES (:id, :company, :shares, :price, :date)",
                   id=session["user_id"], company=stock["symbol"],
                   shares=shares, price=stock["price"],
                   date=datetime.now().isoformat(' ', 'seconds'))

        # update cash in users database
        db.execute("UPDATE users SET cash = cash - :cost WHERE id = :id",
                   cost=price, id=session["user_id"])

        # update transaction in portfolio database
        portfolio = db.execute("SELECT shares FROM portfolio WHERE id=:id AND company=:company",
                               id=session["user_id"], company=stock["symbol"])

        # create portfolio if it does not exist
        if not portfolio:
            db.execute("INSERT INTO portfolio (company, shares, price, id, total) "
                       "VALUES (:company, :shares, :price, :id, :total)",
                       company=stock["symbol"], shares=shares,
                       price=stock["price"], id=session["user_id"],
                       total=(shares * stock["price"]))

        # otherwise update existing portfolio
        else:
            total_shares = portfolio[0]["shares"] + shares
            db.execute("UPDATE portfolio SET shares = :shares WHERE id = :id AND company = :company",
                       shares=total_shares, id=session["user_id"], company=stock["symbol"])

        return redirect("/")

    else:
        return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""

    history = db.execute("SELECT * FROM history WHERE id=:id", id=session["user_id"])

    return render_template("history.html", history=history)


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
    """Get stock quote."""

    if request.method == "POST":
        stocks = lookup(request.form.get("symbol"))
        if not stocks:
            return apology("stock is not valid")
        return render_template("quoted.html", quote=stocks)

    else:
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""

    if request.method == "POST":
        if not request.form.get("username"):
            return apology("Must provide username", 403)
        elif not request.form.get("password"):
            return apology("Must provide password", 403)
        elif not request.form.get("confirmation"):
            return apology("Must confirm password", 403)
        elif request.form.get("password") != request.form.get("confirmation"):
            return apology("Passwords do not match", 403)

        hash = generate_password_hash(request.form.get("password"))

        result = db.execute("INSERT INTO users (username, hash) VALUES (:username, :hash)",
                            username=request.form.get("username"), hash=hash)
        if not result:
            return apology("User already exists", 403)

        user_id = db.execute("SELECT id FROM users WHERE username IS :username",
                             username=request.form.get("username"))
        session["user_id"] = user_id[0]["id"]
        return redirect("/")

    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""

    if request.method == "POST":

        # select data input by the user
        symbol = request.form.get("symbol")
        if not symbol:
            return apology("Must provide a stock")
        try:
            shares = int(request.form.get("shares"))
        except:
            return apology("Must provide number of shares")

        # verify if the data exists in database
        portfolio = db.execute("SELECT shares FROM portfolio WHERE id=:id AND company=:company",
                                  id=session["user_id"], company=symbol)
        if not portfolio:
            return apology("can't sell what you don't have")

        # verify if user owns enough shares to sell
        owned_shares = int(portfolio[0]["shares"])
        if shares > owned_shares:
            return apology("you don't own that many")
        remaining_shares = owned_shares - shares

        # delete entire row if no remaining stocks or update otherwise
        if remaining_shares == 0:
            db.execute("DELETE FROM portfolio WHERE id=:id AND company=:company",
                       company=symbol, id=session["user_id"])
        else:
            db.execute("UPDATE portfolio SET shares=:shares WHERE id=:id AND company=:company",
                       shares=remaining_shares, company=symbol, id=session["user_id"])

        # get the current value of the stock and updated cash value after sale
        user = db.execute("SELECT cash FROM users WHERE id=:id", id=session["user_id"])
        stocks = lookup(symbol)
        current_price = float(stocks["price"])
        cash = float(user[0]["cash"])
        total_cash = cash + (current_price * shares)
        db.execute("UPDATE users SET cash=:cash WHERE id=:id", cash=total_cash, id=session["user_id"])

        # update history database
        db.execute("INSERT INTO history (id, company, shares, price, date) "
                   "VALUES (:id, :company, :shares, :price, :date)",
                   id=session["user_id"], company=symbol,
                   shares=-shares, price=current_price,
                   date=datetime.now().isoformat(' ', 'seconds'))

        return redirect("/")

    else:
        return render_template("sell.html")


def errorhandler(e):
    """Handle error"""
    return apology(e.name, e.code)


# listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
