from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_login import login_required, current_user, login_user, logout_user
from online_restaurant_db import Session, Users, Menu, Orders, Reservation
from flask_login import LoginManager
from datetime import datetime
import os
import uuid
import secrets

app = Flask(__name__)

FILES_PATH = 'static/menu'

app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['MAX_FORM_MEMORY_SIZE'] = 1024 * 1024
app.config['MAX_FORM_PARTS'] = 500
app.config['SESSION_COOKIE_SAMESITE'] = 'Strict'
app.config['SECRET_KEY'] = '#cv)3v7w$*s3fk;5c!@y0?:?№3"9)#'

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    with Session() as session:
        return session.query(Users).filter_by(id=user_id).first()

@app.after_request
def apply_csp(response):
    nonce = secrets.token_urlsafe(16)
    csp = (
        f"default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}'; "
        f"style-src 'self'; "
        f"frame-ancestors 'none'; "
        f"base-uri 'self'; "
        f"form-action 'self'"
    )
    response.headers["Content-Security-Policy"] = csp
    response.set_cookie('nonce', nonce)
    return response

@app.route('/')
@app.route('/home')
def home():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return render_template('base.html')

@app.route("/register", methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if request.form.get("csrf_token") != session["csrf_token"]:
            return "Запит заблоковано!", 403

        nickname = request.form['nickname']
        email = request.form['email']
        password = request.form['password']

        with Session() as cursor:
            if cursor.query(Users).filter_by(email=email).first() or cursor.query(Users).filter_by(nickname=nickname).first():
                flash('Користувач з таким email або нікнеймом вже існує!', 'danger')
            elif len(password) < 8:
                flash('Пароль занадто короткий. Мінімум 8 символів.', 'danger')
                return render_template('register.html', csrf_token=session["csrf_token"])

            new_user = Users(nickname=nickname, email=email)
            new_user.set_password(password)
            cursor.add(new_user)
            cursor.commit()
            cursor.refresh(new_user)
            login_user(new_user)
            return redirect(url_for('home'))
    return render_template('register.html', csrf_token=session["csrf_token"])

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == 'POST':
        if request.form.get("csrf_token") != session["csrf_token"]:
            return "Запит заблоковано!", 403

        nickname = request.form['nickname']
        password = request.form['password']

        with Session() as cursor:
            user = cursor.query(Users).filter_by(nickname=nickname).first()
            if user and user.check_password(password):
                login_user(user)
                return redirect(url_for('home'))

            flash('Неправильний nickname або пароль!', 'danger')

    return render_template('login.html', csrf_token=session["csrf_token"])

@app.route("/add_position", methods=['GET', 'POST'])
@login_required
def add_position():
    if current_user.nickname != 'admin':
        return redirect(url_for('home'))

    if request.method == "POST":
        if request.form.get("csrf_token") != session["csrf_token"]:
            return "Запит заблоковано!", 403

        name = request.form['name']
        file = request.files.get('img')
        ingredients = request.form['ingredients']
        description = request.form['description']
        price = request.form['price']
        weight = request.form['weight']

        if not file or not file.filename:
            return 'Файл не вибрано або завантаження не вдалося'

        unique_filename = f"{uuid.uuid4()}_{file.filename}"
        output_path = os.path.join(FILES_PATH, unique_filename)

        with open(output_path, 'wb') as f:
            f.write(file.read())

        with Session() as cursor:
            new_position = Menu(name=name, ingredients=ingredients, description=description,
                                price=price, weight=weight, file_name=unique_filename)
            cursor.add(new_position)
            cursor.commit()

        flash('Позицію додано успішно!')

    return render_template('add_position.html', csrf_token=session["csrf_token"])

@app.route('/menu')
def menu():
    with Session() as session:
        all_positions = session.query(Menu).filter_by(active=True).all()
    return render_template('menu.html', all_positions=all_positions)

# 🆕 Admin Dashboard
@app.route('/admin')
@login_required
def admin_dashboard():
    if current_user.nickname != 'admin':
        return redirect(url_for('home'))
    return render_template('admin_dashboard.html')

@app.route('/position/<name>', methods=['GET', 'POST'])
def position(name):
    if request.method == 'POST':
        if request.form.get("csrf_token") != session.get("csrf_token"):
            return "Запит заблоковано!", 403

        position_name = request.form.get('name')
        position_num = request.form.get('num')

        if not position_num or int(position_num) <= 0:
            flash("Кількість має бути більшою за 0", "danger")
            return redirect(url_for('position', name=position_name))

        # Отримуємо кошик з сесії або створюємо новий, якщо його немає
        basket = session.get('basket', {})

        # Оновлюємо кількість товару, якщо він вже є в кошику
        if position_name in basket:
            basket[position_name] += int(position_num)
        else:
            basket[position_name] = int(position_num)

        session['basket'] = basket  # Зберігаємо оновлений кошик в сесії
        flash('Позицію додано у кошик!')

    # Завантажуємо позицію з бази даних
    with Session() as cursor:
        us_position = cursor.query(Menu).filter_by(active=True, name=name).first()

    if not us_position:
        flash("Позиція не знайдена!", "danger")
        return redirect(url_for('menu'))

    return render_template('position.html', csrf_token=session["csrf_token"], position=us_position)

@app.route('/basket')
def basket():
    # Отримуємо кошик з сесії
    basket = session.get('basket', {})

    if not basket:
        flash("Ваш кошик порожній", "info")
        return redirect(url_for('menu'))

    # Завантажуємо інформацію про позиції
    with Session() as cursor:
        items = []
        total_price = 0
        for item_name, quantity in basket.items():
            item = cursor.query(Menu).filter_by(name=item_name).first()
            if item:
                total_price += item.price * quantity
                items.append({'name': item.name, 'quantity': quantity, 'price': item.price})

    return render_template('basket.html', items=items, total_price=total_price)

@app.route("/create_order", methods=["POST"])
@login_required
def create_order():
    basket = session.get("basket", {})

    if not basket:
        flash("Кошик порожній", "danger")
        return redirect(url_for("menu"))

    with Session() as db:
        order = Orders(
            order_list=basket,
            order_time=datetime.now(),
            user_id=current_user.id
        )
        db.add(order)
        db.commit()
        session.pop("basket", None)
        flash("Замовлення створено успішно", "success")
        return redirect(url_for("my_orders"))


@app.route('/my_orders')
@login_required
def my_orders():
    with Session() as cursor:
        us_orders = cursor.query(Orders).filter_by(user_id=current_user.id).all()
    return render_template('my_orders.html', us_orders=us_orders)

@app.route("/my_order/<int:id>")
@login_required
def my_order(id):
    with Session() as cursor:
        us_order = cursor.query(Orders).filter_by(id=id).first()
        total_price = sum(int(cursor.query(Menu).filter_by(name=i).first().price) * int(cnt) for i, cnt in us_order.order_list.items())
    return render_template('my_order.html', order=us_order, total_price=total_price)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

if __name__ == "__main__":
    app.run(debug=True)
