import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import socket
import threading
import time
import os
import csv
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# === Настройки ===
MAX_WORKERS = 50

# Папка для логов (рядом с .exe или .py)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

# Глобальный список результатов для экспорта
global_results = []

# === Функции распознавания приглашений ===
def contains_login_prompt(data_bytes):
    if not data_bytes:
        return False
    data = data_bytes.lower()
    return b"name:" in data or b"user:" in data or b"login:" in data

def contains_password_prompt(data_bytes):
    if not data_bytes:
        return False
    data = data_bytes.lower()
    return b"pass" in data or b"ord:" in data

# === Основная функция подключения ===
def send_commands_via_telnet(ip, commands, login, password):
    safe_ip = ip.replace('.', '_')
    debug_file = os.path.join(LOGS_DIR, f"debug_{safe_ip}.log")
    
    def log(msg):
        try:
            with open(debug_file, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now().strftime('%H:%M:%S')} | {msg}\n")
        except:
            pass

    sock = None
    try:
        sock = socket.create_connection((ip, 23), timeout=8)
        sock.setblocking(False)
        log("✅ TCP-подключение установлено")

        # Ждём начальные данные
        buffer = b""
        start = time.time()
        while time.time() - start < 3.0:
            try:
                data = sock.recv(1024)
                if data:
                    buffer += data
            except BlockingIOError:
                time.sleep(0.1)
            except:
                break
        log(f"[RX INITIAL] {repr(buffer)}")

        # Если нет приглашения — отправляем \r\n
        if not contains_login_prompt(buffer):
            sock.send(b"\r\n")
            log("📤 Отправлен \\r\\n")
            time.sleep(0.8)

            buffer2 = b""
            start = time.time()
            while time.time() - start < 3.0:
                try:
                    data = sock.recv(1024)
                    if data:
                        buffer2 += data
                except BlockingIOError:
                    time.sleep(0.1)
                except:
                    break
            buffer += buffer2
            log(f"[RX AFTER CRLF] {repr(buffer)}")

        if not contains_login_prompt(buffer):
            log("❌ Логин не найден")
            return False, "Приглашение логина не получено"

        # Отправляем логин
        sock.send(login.encode() + b"\r\n")
        log("📤 Логин отправлен")
        time.sleep(0.5)

        # Читаем приглашение пароля
        buffer_pass = b""
        start = time.time()
        while time.time() - start < 2.0:
            try:
                data = sock.recv(1024)
                if data:
                    buffer_pass += data
            except BlockingIOError:
                time.sleep(0.1)
            except:
                break
        log(f"[RX PASS PROMPT] {repr(buffer_pass)}")

        if not contains_password_prompt(buffer_pass):
            log("❌ Пароль не найден")
            return False, "Приглашение пароля не получено"

        # Отправляем пароль
        sock.send(password.encode() + b"\r\n")
        log("📤 Пароль отправлен")
        time.sleep(1.0)

        # Читаем CLI
        buffer_cli = b""
        start = time.time()
        while time.time() - start < 3.0:
            try:
                data = sock.recv(1024)
                if data:
                    buffer_cli += data
                    if b"#" in data:
                        break
            except BlockingIOError:
                time.sleep(0.2)
            except:
                break
        log(f"[RX CLI] {repr(buffer_cli)}")
        if b"#" not in buffer_cli:
            return False, "CLI не готов"

        # Выполняем команды
        for cmd in commands:
            cmd = cmd.strip()
            if not cmd:
                continue
            sock.send(cmd.encode() + b"\r\n")
            log(f"📤 Команда: {cmd}")
            time.sleep(0.8)

            resp = b""
            start = time.time()
            while time.time() - start < 3.0:
                try:
                    data = sock.recv(1024)
                    if data:
                        resp += data
                        if b"#" in data:
                            break
                except BlockingIOError:
                    time.sleep(0.2)
                except:
                    break
            log(f"[RX] {repr(resp)}")

        sock.close()
        log("✅ Успешно")
        return True, "Успешно"

    except Exception as e:
        log(f"❗ Исключение: {repr(e)}")
        try:
            if sock:
                sock.close()
        except:
            pass
        return False, str(e)

# === Запуск конфигурации ===
def run_configuration():
    global global_results
    login = entry_login.get().strip()
    password = entry_password.get().strip()
    ips = [ip.strip() for ip in text_ips.get("1.0", tk.END).splitlines() if ip.strip()]
    commands = [cmd.strip() for cmd in text_cmds.get("1.0", tk.END).splitlines() if cmd.strip()]

    if not login or not password:
        messagebox.showwarning("Ошибка", "Введите логин и пароль!")
        return
    if not ips or not commands:
        messagebox.showwarning("Ошибка", "Введите хотя бы один IP и одну команду!")
        return

    total = len(ips)
    global_results = []
    completed = 0
    start_time = time.time()

    # Сброс интерфейса
    progress_label.config(text=f"Обработано: 0 / {total}")
    metrics_label.config(text="Скорость: —  |  Осталось: —")
    progress_bar["value"] = 0
    progress_bar["maximum"] = total

    for row in tree.get_children():
        tree.delete(row)

    def worker():
        nonlocal completed
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(send_commands_via_telnet, ip, commands, login, password): ip
                for ip in ips
            }
            results = []
            for future in as_completed(futures):
                ip = futures[future]
                success, msg = future.result()
                status = "Успешно" if success else "Ошибка"
                results.append((ip, status, msg))

                completed += 1
                current_time = time.time()
                elapsed = current_time - start_time
                speed = completed / elapsed if elapsed > 0 else 0
                remaining = (total - completed) / speed if speed > 0 else 0

                if remaining < 60:
                    remaining_str = f"{int(remaining)} сек"
                elif remaining < 3600:
                    remaining_str = f"{int(remaining // 60)} мин"
                else:
                    remaining_str = f"{int(remaining // 3600)} ч"
                speed_str = f"{speed:.1f} шт/сек"

                def update_ui():
                    progress_label.config(text=f"Обработано: {completed} / {total}")
                    progress_bar["value"] = completed
                    metrics_label.config(text=f"Скорость: {speed_str}  |  Осталось: ~{remaining_str}")

                    tag = "success" if success else "error"
                    tree.insert("", "end", values=(ip, status, msg), tags=(tag,))

                root.after(0, update_ui)

            def final_update():
                global global_results
                global_results = results
                messagebox.showinfo("Готово", f"Обработка завершена!\nЛоги: папка '{os.path.basename(LOGS_DIR)}'")
            root.after(0, final_update)

    threading.Thread(target=worker, daemon=True).start()

# === Экспорт в CSV ===
def export_to_csv():
    if not global_results:
        messagebox.showinfo("Экспорт", "Нет данных для экспорта.")
        return

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    default_name = f"report_{timestamp}.csv"
    filepath = filedialog.asksaveasfilename(
        title="Сохранить отчёт",
        initialfile=default_name,
        defaultextension=".csv",
        filetypes=[("CSV файлы", "*.csv"), ("Все файлы", "*.*")]
    )
    if not filepath:
        return

    try:
        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["IP-адрес", "Статус", "Сообщение"])
            writer.writerows(global_results)
        messagebox.showinfo("Экспорт", f"Отчёт сохранён:\n{filepath}")
    except Exception as e:
        messagebox.showerror("Ошибка", f"Не удалось сохранить файл:\n{str(e)}")

# === GUI ===
root = tk.Tk()
root.title("Mass Switch Configurator — D-Link / SNR (Telnet)")
root.geometry("1000x780")
root.minsize(900, 620)

tk.Label(root, text="IP-адреса коммутаторов (по одному на строку):").pack(anchor="w", padx=10, pady=(10, 0))
text_ips = tk.Text(root, height=6, font=("Consolas", 10))
text_ips.pack(fill=tk.BOTH, padx=10, pady=5)

# === Поля логина и пароля ===
auth_frame = tk.Frame(root)
auth_frame.pack(fill=tk.X, padx=10, pady=5)

tk.Label(auth_frame, text="Логин:", width=10, anchor="w").pack(side="left")
entry_login = tk.Entry(auth_frame, font=("Consolas", 10))
entry_login.pack(side="left", fill=tk.X, expand=True, padx=(5, 20))
entry_login.insert(0, "admin")

tk.Label(auth_frame, text="Пароль:", width=10, anchor="w").pack(side="left")
entry_password = tk.Entry(auth_frame, font=("Consolas", 10), show="*")
entry_password.pack(side="left", fill=tk.X, expand=True, padx=(5, 0))
entry_password.insert(0, "123456")

tk.Label(root, text="CLI-команды (по одной на строку; добавьте 'save', если нужно сохранить):").pack(anchor="w", padx=10)
text_cmds = tk.Text(root, height=5, font=("Consolas", 10))
text_cmds.pack(fill=tk.BOTH, padx=10, pady=5)

# Кнопки
btn_frame = tk.Frame(root)
btn_frame.pack(pady=5)

tk.Button(
    btn_frame, text="🚀 Запустить", command=run_configuration,
    bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), padx=20
).pack(side="left", padx=5)

tk.Button(
    btn_frame, text="💾 Сохранить отчёт в CSV", command=export_to_csv,
    bg="#FF9800", fg="white", font=("Arial", 10), padx=15
).pack(side="left", padx=5)

# Прогресс
progress_frame = tk.Frame(root)
progress_frame.pack(pady=5)

progress_label = tk.Label(progress_frame, text="Обработано: 0 / 0", font=("Arial", 10))
progress_label.pack(side="left", padx=(10, 10))

progress_bar = ttk.Progressbar(progress_frame, orient="horizontal", length=350, mode="determinate")
progress_bar.pack(side="left", padx=(0, 10))

metrics_label = tk.Label(progress_frame, text="Скорость: —  |  Осталось: —", font=("Arial", 9), fg="gray")
metrics_label.pack(side="left")

# Таблица
frame_tree = tk.Frame(root)
frame_tree.pack(fill=tk.BOTH, padx=10, pady=10, expand=True)

columns = ("IP", "Status", "Message")
tree = ttk.Treeview(frame_tree, columns=columns, show="headings", height=18)
tree.heading("IP", text="IP-адрес")
tree.heading("Status", text="Статус")
tree.heading("Message", text="Сообщение")
tree.column("IP", width=130, anchor="w")
tree.column("Status", width=100, anchor="center")
tree.column("Message", width=720, anchor="w")

# Цвета
tree.tag_configure("success", foreground="green")
tree.tag_configure("error", foreground="red")

v_scroll = ttk.Scrollbar(frame_tree, orient="vertical", command=tree.yview)
tree.configure(yscrollcommand=v_scroll.set)
v_scroll.pack(side="right", fill="y")
tree.pack(side="left", fill="both", expand=True)

root.mainloop()