#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Генератор импульсов v3‑u4 (модифицирован)
— каждый сигнал рисуется в одном окне, друг‑под‑другом
— тики оси X выводят число + единицу измерения (ns, µs…)
— добавлена настройка шага тиков оси X (e.g., '10ns', '0.5us')
— возможность загрузки списка сигналов из файла (форматы PULSE и PWL)
— можно менять порядок сигналов перетаскиванием мышью или Ctrl+↑/↓
— добавлена возможность выбора режима ввода параметров: либо T_HIGH и T_LOW, либо T_PULSE_WIDTH и T_PERIOD
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import numpy as np

# ───── Вспомогательные функции времени ─────
_UNITS = {'n': 1e-9, 'u': 1e-6, 'm': 1e-3,
          'k': 1e3, 'meg': 1e6, 'g': 1e9, '': 1}

def parse_time(s: str) -> float:
    """Преобразует строку (например, '10ns', '5 u', '0.1 m') в секунды."""
    s = str(s).strip().lower()
    if not s:
        raise ValueError("Пустая строка времени")
    m = re.fullmatch(r'([0-9.]+(?:e[+-]?[0-9]+)?)\s*([a-z]*)s?', s)
    if not m:
        raise ValueError(f'Неверный формат времени: "{s}"')
    v_str, u = m.groups()
    try:
        v = float(v_str)
    except ValueError:
        raise ValueError(f'Неверное числовое значение: "{v_str}"')
    unit_prefix = u
    if u == 'micro':
        unit_prefix = 'u'
    elif u == 'nano':
        unit_prefix = 'n'
    elif u == 'milli':
        unit_prefix = 'm'
    elif u == 'kilo':
        unit_prefix = 'k'
    elif u == 'mega':
        unit_prefix = 'meg'
    elif u == 'giga':
        unit_prefix = 'g'
    if unit_prefix not in _UNITS:
        if unit_prefix == '':
             unit_prefix = ''
        else:
            raise ValueError(f'Неизвестная единица измерения: "{u}"')
    multiplier = _UNITS[unit_prefix]
    result = v * multiplier
    if result < 0:
         raise ValueError("Время не может быть отрицательным")
    return result

def fmt(sec: float) -> str:
    """Форматирует время в строку с единицей измерения (автомасштабирование)."""
    a = abs(sec)
    if a == 0:
        return '0'
    if a >= 1:
        return f'{sec:.4g}'
    elif a >= 1e-3:
        return f'{sec*1e3:.4g}m'
    elif a >= 1e-6:
        return f'{sec*1e6:.4g}u'
    elif a >= 1e-9:
        return f'{sec*1e9:.4g}n'
    else:
        return f'{sec:.4g}'

def autoscale(total: float) -> tuple[float, str]:
    """Определяет множитель и единицу измерения для оси X."""
    if total <= 0:
        return 1, 's'
    if total <= 1e-6:
        return 1e9, 'ns'
    if total <= 1e-3:
        return 1e6, 'µs'
    if total < 1:
        return 1e3, 'ms'
    return 1, 's'

def unit_formatter(unit: str):
    """Возвращает форматер оси X для Matplotlib."""
    unit_str = f' {unit}' if unit and unit != 's' else ' s'
    return ticker.FuncFormatter(lambda x, pos: f'{x:g}{unit_str}')

# ───── Data class сигнала ─────
@dataclass
class Signal:
    V0: float; V1: float
    TD: float; TR: float; TF: float; TH: float; TL: float
    N: int;   Name: str
    tp: float = field(init=False)
    total_time: float = field(init=False)
    scale: float = field(init=False); unit: str = field(init=False)
    
    def __post_init__(self):
        self.update()
    
    def update(self):
        """Пересчитывает дополнительные параметры сигнала."""
        self.TR = max(0, self.TR)
        self.TF = max(0, self.TF)
        self.TH = max(0, self.TH)
        self.TL = max(0, self.TL)
        self.TD = max(0, self.TD)
        self.N = max(0, self.N)
        self.tp = self.TR + self.TH + self.TF + self.TL
        self.total_time = self.TD if self.N == 0 else self.TD + self.N * self.tp
        self.scale, self.unit = autoscale(self.total_time)
    
    def get_waveform_points(self) -> tuple[list[float], list[float]]:
        """
        Генерирует точки (t, v) для построения графика сигнала.
        """
        times: list[float] = []
        voltages: list[float] = []
        t_cur = 0.0
        times.append(0.0)
        voltages.append(self.V0)
        if self.TD > 0:
            t_cur += self.TD
            times.append(t_cur)
            voltages.append(self.V0)
        if self.N > 0 and self.tp > 0:
            for i in range(self.N):
                if self.TR > 0:
                    t_cur += self.TR
                    times.append(t_cur)
                    voltages.append(self.V1)
                if self.TH > 0:
                    t_cur += self.TH
                    times.append(t_cur)
                    voltages.append(self.V1)
                if self.TF > 0:
                    t_cur += self.TF
                    times.append(t_cur)
                    voltages.append(self.V0)
                if self.TL > 0:
                    t_cur += self.TL
                    times.append(t_cur)
                    voltages.append(self.V0)
        else:
            t_cur = self.TD
        theoretical_end = self.TD if self.N == 0 else self.TD + self.N * self.tp
        if not times or abs(t_cur - theoretical_end) > 1e-12:
            last_v = voltages[-1] if voltages else self.V0
            times.append(theoretical_end)
            voltages.append(last_v)
        return times, voltages

# ───── Главное приложение ─────
class PulseApp(ttk.Frame):
    # Поля сигнала. Обратите внимание – для режима T_PULSE_WIDTH/T_PERIOD поля 'TH' и 'TL' будут переименованы.
    FIELDS = (('V0','Ур0'), ('V1','Ур1'), ('TD','Delay'), ('TR','Rise'),
              ('TF','Fall'), ('TH','High'), ('TL','Low'), ('N','Cnt'), ('Name','Имя'))
    
    def __init__(self, master: tk.Tk):
        super().__init__(master)
        self.pack(fill='both', expand=True)
        master.title('Impulse generator v3‑u4')
        master.minsize(750, 550)
        self.signals: list[Signal] = []
        self._drag_start_index = None
        self.mode = "high-low"  # режим по умолчанию
        self._style()
        self._layout()
        self._mpl()

    # ─ style
    def _style(self):
        st = ttk.Style()
        st.theme_use('clam')
        st.configure('TButton', font=('Segoe UI', 10))
        st.configure('TLabel', font=('Segoe UI', 10))
        st.configure('TEntry', font=('Segoe UI', 10))
        st.configure('TLabelframe.Label', font=('Segoe UI', 10, 'bold'))

    # ─ layout
    def _layout(self):
        # Основное окно с PanedWindow (левая панель — список сигналов, правая — график)
        main_paned = ttk.PanedWindow(self, orient='horizontal')
        main_paned.pack(fill='both', expand=True, padx=5, pady=(5, 0))
        # Левая панель
        left_frame = ttk.Frame(main_paned, padding=5)
        main_paned.add(left_frame, weight=1)
        self.lb = tk.Listbox(left_frame, exportselection=False, font=('Segoe UI', 10), height=10)
        self.lb.pack(fill='both', expand=True)
        self.lb.bind('<<ListboxSelect>>', self.on_select)
        self.lb.bind('<ButtonPress-1>', self.on_lb_button_press)
        self.lb.bind('<B1-Motion>', self.on_lb_motion)
        self.lb.bind('<Control-Up>', self.move_item_up)
        self.lb.bind('<Control-Down>', self.move_item_down)
        list_buttons_frame = ttk.Frame(left_frame)
        list_buttons_frame.pack(fill='x', pady=(5, 0))
        btn_configs = (('Load', self.load),
                       ('Add', self.add),
                       ('Del', self.delete),
                       ('Export', self.export))
        for i, (text, cmd) in enumerate(btn_configs):
            btn = ttk.Button(list_buttons_frame, text=text, command=cmd)
            btn.pack(side='left', expand=True, fill='x', padx=(0, 2) if i < len(btn_configs)-1 else 0)
        # Правая панель – для графика
        self.plot_fr = ttk.Frame(main_paned, padding=0)
        main_paned.add(self.plot_fr, weight=4)
        # Панель редактирования параметров сигнала и графика
        editor_frame = ttk.LabelFrame(self, text='Параметры сигнала и графика', padding=10)
        editor_frame.pack(fill='x', padx=5, pady=5)
        
        # Ряд для выбора режима (row 0)
        mode_frame = ttk.Frame(editor_frame)
        mode_frame.grid(row=0, column=0, columnspan=4, sticky='ew', pady=(0, 10))
        ttk.Label(mode_frame, text="Режим:").pack(side='left')
        self.mode_var = tk.StringVar(value="T_HIGH/T_LOW")
        self.mode_combobox = ttk.Combobox(mode_frame, textvariable=self.mode_var, state="readonly",
                                          values=["T_HIGH/T_LOW", "T_PULSE_WIDTH/T_PERIOD"])
        self.mode_combobox.pack(side='left', padx=5)
        self.mode_combobox.bind("<<ComboboxSelected>>", self.on_mode_change)
        
        # Поля задания параметров сигнала (используем self.FIELDS). Ряды с 1 по 9.
        self.ent: dict[str, ttk.Entry] = {}
        self.param_labels: dict[str, ttk.Label] = {}
        col_param = 0
        for i, (k, lbl) in enumerate(self.FIELDS):
            # Для полей TH и TL в зависимости от режима меняем подписи
            actual_lbl = lbl
            if k == 'TH':
                actual_lbl = "High" if self.mode == "high-low" else "PW"
            elif k == 'TL':
                actual_lbl = "Low" if self.mode == "high-low" else "Period"
            label_widget = ttk.Label(editor_frame, text=actual_lbl+':')
            label_widget.grid(row=i+1, column=col_param, sticky='e', padx=(0,5), pady=2)
            self.param_labels[k] = label_widget
            entry_widget = ttk.Entry(editor_frame, width=12, font=('Segoe UI', 10))
            entry_widget.grid(row=i+1, column=col_param+1, sticky='ew', padx=4, pady=1)
            self.ent[k] = entry_widget
        
        # Параметры графика. Помещаем в столбцах 2–3; здесь для примера X‑max и шаг тиков.
        col_graph = 2
        ttk.Label(editor_frame, text='X‑max:').grid(row=1, column=col_graph, sticky='e', padx=(15,5), pady=2)
        self.xmax_var = tk.StringVar(value='auto')
        ttk.Entry(editor_frame, textvariable=self.xmax_var, width=10, font=('Segoe UI', 10)).grid(row=1, column=col_graph+1, sticky='ew', padx=4, pady=1)
        
        ttk.Label(editor_frame, text='Шаг тиков X:').grid(row=2, column=col_graph, sticky='e', padx=(15,5), pady=2)
        self.xtick_step_var = tk.StringVar(value='auto')
        self.xtick_step_entry = ttk.Entry(editor_frame, textvariable=self.xtick_step_var, width=10, font=('Segoe UI', 10))
        self.xtick_step_entry.grid(row=2, column=col_graph+1, sticky='ew', padx=4, pady=1)
        
        # Кнопка применения. Располагаем в ряду = len(FIELDS)+1 (то есть row 10)
        apply_btn = ttk.Button(editor_frame, text='Применить / Обновить график', command=self.apply_and_draw)
        apply_btn.grid(row=len(self.FIELDS)+1, column=0, columnspan=4, pady=(10, 0), sticky='ew')
        editor_frame.columnconfigure(col_param+1, weight=1)
        editor_frame.columnconfigure(col_graph+1, weight=1)

    # ─ mpl объекты
    def _mpl(self):
        self.fig = plt.Figure(figsize=(6, 4), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.plot_fr)
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(fill='both', expand=True)
        toolbar_frame = ttk.Frame(self.plot_fr)
        toolbar_frame.pack(fill='x', side='bottom')
        self.toolbar = NavigationToolbar2Tk(self.canvas, toolbar_frame, pack_toolbar=False)
        self.toolbar.update()
        self.toolbar.pack(fill='x')
        self.canvas.draw_idle()

    # При изменении режима обновляем подписи полей TH и TL
    def on_mode_change(self, event):
        mode_sel = self.mode_var.get()
        if mode_sel == "T_HIGH/T_LOW":
            self.mode = "high-low"
        else:
            self.mode = "pw-period"
        if 'TH' in self.param_labels:
            new_lbl_th = "High" if self.mode == "high-low" else "PW"
            self.param_labels['TH'].config(text=new_lbl_th + ':')
        if 'TL' in self.param_labels:
            new_lbl_tl = "Low" if self.mode == "high-low" else "Period"
            self.param_labels['TL'].config(text=new_lbl_tl + ':')

    # ─ Чтение данных сигнала из полей ввода
    def _read_signal_data(self) -> Signal:
        v = {k: self.ent[k].get().strip() for k, _ in self.FIELDS}
        try:
            name = v['Name'] if v['Name'] else f'Signal {len(self.signals)+1}'
            v0 = float(v['V0'] or 0)
            v1 = float(v['V1'] or 1)
            td = parse_time(v['TD'] or "0")
            tr = parse_time(v['TR'] or "1n")
            tf = parse_time(v['TF'] or "1n")
            if self.mode == "high-low":
                th = parse_time(v['TH'] or "1u")
                tl = parse_time(v['TL'] or "1u")
            else:
                # Режим T_PULSE_WIDTH/T_PERIOD: поле 'TH' содержит T_PULSE_WIDTH, 'TL' – T_PERIOD
                pulse_width = parse_time(v['TH'] or "1u")
                period = parse_time(v['TL'] or "1u")
                if pulse_width < (tr + tf):
                    raise ValueError("T_PULSE_WIDTH должен быть не меньше TR + TF.")
                if period < pulse_width:
                    raise ValueError("T_PERIOD должен быть не меньше T_PULSE_WIDTH.")
                th = pulse_width - tr - tf
                tl = period - pulse_width
            n = int(v['N'] or 1)
            return Signal(V0=v0, V1=v1, TD=td, TR=tr, TF=tf, TH=th, TL=tl, N=n, Name=name)
        except ValueError as e:
            raise ValueError(f"Ошибка в параметрах сигнала: {e}")
        except Exception as e:
            raise ValueError(f"Неожиданная ошибка чтения параметров: {e}")

    def _get_selected_index(self):
        s = self.lb.curselection()
        return int(s[0]) if s else None

    # ─ Методы для изменения порядка элементов
    def move_in_list(self, from_index: int, to_index: int):
        if from_index == to_index:
            return
        sig = self.signals.pop(from_index)
        self.signals.insert(to_index, sig)
        label = self.lb.get(from_index)
        self.lb.delete(from_index)
        self.lb.insert(to_index, label)
        self.lb.select_clear(0, 'end')
        self.lb.selection_set(to_index)
        self.lb.activate(to_index)
        self.draw()

    def on_lb_button_press(self, event):
        self._drag_start_index = self.lb.nearest(event.y)

    def on_lb_motion(self, event):
        cur_index = self.lb.nearest(event.y)
        if cur_index != self._drag_start_index:
            self.move_in_list(self._drag_start_index, cur_index)
            self._drag_start_index = cur_index

    def move_item_up(self, event):
        i = self._get_selected_index()
        if i is not None and i > 0:
            self.move_in_list(i, i - 1)
        return "break"

    def move_item_down(self, event):
        i = self._get_selected_index()
        if i is not None and i < self.lb.size() - 1:
            self.move_in_list(i, i + 1)
        return "break"

    def add(self):
        try:
            s = self._read_signal_data()
        except ValueError as e:
            messagebox.showerror('Ошибка ввода', str(e))
            return
        self.signals.append(s)
        self.lb.insert('end', s.Name)
        self.lb.select_clear(0, 'end')
        self.lb.selection_set('end')
        self.lb.activate('end')
        self.lb.see('end')
        self.on_select()
        self.draw()

    def delete(self):
        i = self._get_selected_index()
        if i is None:
            messagebox.showwarning("Нет выбора", "Сначала выберите сигнал для удаления.")
            return
        if 0 <= i < len(self.signals):
            confirm = messagebox.askyesno("Подтверждение", f"Удалить сигнал '{self.signals[i].Name}'?")
            if confirm:
                self.lb.delete(i)
                self.signals.pop(i)
                if self.lb.size() > 0:
                    new_selection = min(i, self.lb.size() - 1)
                    self.lb.selection_set(new_selection)
                    self.lb.activate(new_selection)
                    self.on_select()
                else:
                    self._clear_entries()
                self.draw()
        else:
             messagebox.showerror("Ошибка", "Не удалось удалить сигнал: неверный индекс.")

    def apply_and_draw(self):
        i = self._get_selected_index()
        if i is not None:
            if 0 <= i < len(self.signals):
                try:
                    original_name = self.signals[i].Name
                    updated_signal = self._read_signal_data()
                    if not updated_signal.Name:
                        updated_signal.Name = original_name
                    self.signals[i] = updated_signal
                    if self.lb.get(i) != updated_signal.Name:
                        self.lb.delete(i)
                        self.lb.insert(i, updated_signal.Name)
                        self.lb.select_set(i)
                except ValueError as e:
                    messagebox.showerror('Ошибка ввода', str(e))
                except Exception as e:
                    messagebox.showerror('Ошибка применения', f"Не удалось применить изменения: {e}")
        self.draw()

    def export(self):
        """
        Экспортирует данные сигналов в файл.
          – PULSE: формат "Имя:PULSE(V0 V1 TD TR TF TH tp N)"
          – PWL  : формат "Имя:PWL(t0 v0 t1 v1 …)"
        """
        if not self.signals:
            messagebox.showinfo('Экспорт', 'Нет сигналов для экспорта.')
            return
        format_choice = simpledialog.askstring("Формат экспорта", 
                                                 "Введите формат экспорта (PULSE или PWL):", 
                                                 initialvalue="PULSE")
        if not format_choice:
            messagebox.showwarning("Экспорт", "Формат не выбран, экспорт отменен.")
            return
        format_choice = format_choice.strip().upper()
        filepath = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialfile="signals.txt",
            title="Сохранить сигналы как..."
        )
        if not filepath:
            return
        try:
            with open(filepath, 'w', encoding='utf‑8') as f:
                if format_choice == "PWL":
                    for s in self.signals:
                        times, voltages = s.get_waveform_points()
                        points_str = " ".join(f"{t:g} {v:g}" for t, v in zip(times, voltages))
                        f.write(f"{s.Name}:PWL({points_str})\n")
                else:
                    for s in self.signals:
                        f.write(f"{s.Name}:PULSE({s.V0:g} {s.V1:g} {s.TD} {s.TR} {s.TF} {s.TH} {s.tp} {s.N})\n")
            messagebox.showinfo('Экспорт завершен', f'Сигналы сохранены в файл:\n{filepath}')
        except IOError as e:
            messagebox.showerror("Ошибка записи", f"Не удалось сохранить файл:\n{e}")

    def load(self):
        """Загружает сигналы из выбранного файла и отображает их на графике."""
        filepath = filedialog.askopenfilename(
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Загрузить сигналы из файла"
        )
        if not filepath:
            return
        try:
            with open(filepath, 'r', encoding='utf‑8') as f:
                lines = f.readlines()
        except IOError as e:
            messagebox.showerror("Ошибка чтения", f"Не удалось открыть файл:\n{e}")
            return
        self.signals.clear()
        self.lb.delete(0, 'end')
        for lineno, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue
            try:
                if ':' not in line:
                    raise ValueError("Отсутствует разделитель ':'")
                name_part, data_part = line.split(':', 1)
                name = name_part.strip()
                data_part = data_part.strip()
                if data_part.startswith("PULSE(") and data_part.endswith(")"):
                    inner = data_part[len("PULSE("):-1].strip()
                    tokens = inner.split()
                    if len(tokens) != 8:
                        raise ValueError(f"Ожидалось 8 значений для PULSE, получено {len(tokens)}")
                    v0 = float(tokens[0])
                    v1 = float(tokens[1])
                    TD = float(tokens[2])
                    TR = float(tokens[3])
                    TF = float(tokens[4])
                    TH = float(tokens[5])
                    tp = float(tokens[6])
                    N = int(tokens[7])
                    TL = tp - (TR + TF + TH)
                    if TL < 0:
                        raise ValueError("Вычисленное значение TL < 0")
                    sig = Signal(V0=v0, V1=v1, TD=TD, TR=TR, TF=TF, TH=TH, TL=TL, N=N, Name=name)
                    sig.update()
                    self.signals.append(sig)
                elif data_part.startswith("PWL(") and data_part.endswith(")"):
                    inner = data_part[len("PWL("):-1].strip()
                    tokens = inner.split()
                    if len(tokens) % 2 != 0:
                        raise ValueError("Нечетное число значений в PWL")
                    points = []
                    for i in range(0, len(tokens), 2):
                        t_val = float(tokens[i])
                        v_val = float(tokens[i+1])
                        points.append((t_val, v_val))
                    if len(points) < 2:
                        raise ValueError("Недостаточно точек в PWL")
                    V0 = points[0][1]
                    TD = points[1][0]
                    if len(points) == 2:
                        TR = TF = TH = TL = 0
                        N = 0
                        V1 = V0
                    else:
                        if len(points) < 6:
                            raise ValueError("Недостаточно точек для одного импульса в PWL")
                        TR = points[2][0] - points[1][0]
                        TH = points[3][0] - points[2][0]
                        TF = points[4][0] - points[3][0]
                        TL = points[5][0] - points[4][0]
                        if (len(points) - 2) % 4 == 0:
                            N = (len(points) - 2) // 4
                        elif (len(points) - 2) % 4 == 1:
                            N = ((len(points) - 2) - 1) // 4
                        else:
                            raise ValueError("Неверное число точек для формирования повторяющихся импульсов")
                        V1 = points[2][1]
                    sig = Signal(V0=V0, V1=V1, TD=TD, TR=TR, TF=TF, TH=TH, TL=TL, N=N, Name=name)
                    sig.update()
                    self.signals.append(sig)
                else:
                    raise ValueError("Неизвестный формат: должна начинаться с PULSE( или PWL(")
                self.lb.insert('end', name)
            except Exception as ex:
                messagebox.showerror("Ошибка парсинга", f"Ошибка в строке {lineno}: {line}\n{ex}")
        self.draw()
        messagebox.showinfo("Загрузка завершена", f"Загружено {len(self.signals)} сигнал(ов) из файла.")

    def on_select(self, event=None):
        i = self._get_selected_index()
        if i is None:
            return
        if 0 <= i < len(self.signals):
            s = self.signals[i]
            self._update_entries(s)

    def _update_entries(self, signal: Signal):
         self.ent['V0'].delete(0, 'end'); self.ent['V0'].insert(0, f"{signal.V0:g}")
         self.ent['V1'].delete(0, 'end'); self.ent['V1'].insert(0, f"{signal.V1:g}")
         self.ent['TD'].delete(0, 'end'); self.ent['TD'].insert(0, fmt(signal.TD))
         self.ent['TR'].delete(0, 'end'); self.ent['TR'].insert(0, fmt(signal.TR))
         self.ent['TF'].delete(0, 'end'); self.ent['TF'].insert(0, fmt(signal.TF))
         if self.mode == "high-low":
             self.ent['TH'].delete(0, 'end'); self.ent['TH'].insert(0, fmt(signal.TH))
             self.ent['TL'].delete(0, 'end'); self.ent['TL'].insert(0, fmt(signal.TL))
         else:
             # В режиме импульсной ширины/периода
             pulse_width = signal.TR + signal.TH + signal.TF
             period = signal.tp
             self.ent['TH'].delete(0, 'end'); self.ent['TH'].insert(0, fmt(pulse_width))
             self.ent['TL'].delete(0, 'end'); self.ent['TL'].insert(0, fmt(period))
         self.ent['N'].delete(0, 'end'); self.ent['N'].insert(0, signal.N)
         self.ent['Name'].delete(0, 'end'); self.ent['Name'].insert(0, signal.Name)

    def _clear_entries(self):
        for key in self.ent:
            self.ent[key].delete(0, 'end')

    # ─ Рисование графиков
    def draw(self):
        self.fig.clf()
        if not self.signals:
            ax = self.fig.add_subplot(111)
            ax.text(0.5, 0.5, "Нет сигналов для отображения.\nДобавьте сигнал с помощью кнопки 'Add'.",
                    ha='center', va='center', fontsize=12, color='gray')
            ax.set_xticks([])
            ax.set_yticks([])
            self.canvas.draw_idle()
            return
        xmax_str = self.xmax_var.get().strip().lower()
        xmax_sec_global = None
        try:
            if xmax_str not in ('', 'auto'):
                xmax_sec_global = parse_time(xmax_str)
                if xmax_sec_global <= 0:
                    print("Warning: X-max должен быть больше нуля. Используется auto.")
                    xmax_sec_global = None
                    self.xmax_var.set('auto')
        except ValueError as e:
            print(f"Warning: Неверное значение X-max '{xmax_str}'. Используется auto. Ошибка: {e}")
            xmax_sec_global = None
            self.xmax_var.set('auto')
        xtick_step_str = self.xtick_step_var.get().strip().lower()
        tick_step_sec = None
        if xtick_step_str not in ('', 'auto'):
             try:
                 tick_step_sec = parse_time(xtick_step_str)
                 if tick_step_sec <= 0:
                     print(f"Warning: Шаг тиков '{xtick_step_str}' должен быть положительным. Используется auto.")
                     tick_step_sec = None
                     self.xtick_step_var.set('auto')
             except ValueError as e:
                 print(f"Warning: Неверный формат шага тиков '{xtick_step_str}'. Используется auto. Ошибка: {e}")
                 tick_step_sec = None
                 self.xtick_step_var.set('auto')
        n_signals = len(self.signals)
        idx_sel = self._get_selected_index()
        common_scale, common_unit = (1, 's')
        if xmax_sec_global is not None:
            common_scale, common_unit = autoscale(xmax_sec_global)
        for i, s in enumerate(self.signals):
            ax = self.fig.add_subplot(n_signals, 1, i + 1)
            current_scale, current_unit = (common_scale, common_unit) if xmax_sec_global is not None else (s.scale, s.unit)
            t_scaled = [0]
            v = [s.V0]
            t_cur_sec = 0
            if s.TD > 0:
                t_cur_sec += s.TD
                t_scaled.append(t_cur_sec * current_scale)
                v.append(s.V0)
            pulse_end_time_sec = t_cur_sec
            if s.N > 0 and s.tp > 0:
                 for k in range(s.N):
                     if s.TR > 0:
                         t_cur_sec += s.TR
                         t_scaled.append(t_cur_sec * current_scale)
                         v.append(s.V1)
                     if s.TH > 0:
                         t_cur_sec += s.TH
                         t_scaled.append(t_cur_sec * current_scale)
                         v.append(s.V1)
                     if s.TF > 0:
                         t_cur_sec += s.TF
                         t_scaled.append(t_cur_sec * current_scale)
                         v.append(s.V0)
                     if s.TL > 0:
                         t_cur_sec += s.TL
                         t_scaled.append(t_cur_sec * current_scale)
                         v.append(s.V0)
                     pulse_end_time_sec = t_cur_sec
            else:
                 pulse_end_time_sec = s.TD
            theoretical_end_sec = s.TD if s.N == 0 else s.TD + s.N * s.tp
            if not t_scaled or abs(t_cur_sec - theoretical_end_sec) > 1e-12:
                 if len(v) > 0:
                      last_v = v[-1]
                      if s.N == 0:
                          last_v = s.V0
                      t_scaled.append(theoretical_end_sec * current_scale)
                      v.append(last_v)
            if t_scaled:
                ax.plot(t_scaled, v, lw=1.5, color='C0')
            title_style = {'fontweight': 'bold', 'color': 'darkblue'} if i == idx_sel else {}
            ax.set_title(s.Name, fontsize=10, loc='left', **title_style)
            ax.set_ylabel('V', fontsize=9)
            v_min_data = min(v) if v else s.V0
            v_max_data = max(v) if v else s.V1
            v_min, v_max = min(s.V0, s.V1, v_min_data), max(s.V0, s.V1, v_max_data)
            v_range = v_max - v_min if v_max != v_min else 1.0
            ax.set_ylim(v_min - v_range * 0.15, v_max + v_range * 0.15)
            xmax_limit_sec = xmax_sec_global if xmax_sec_global is not None else theoretical_end_sec
            xmax_limit_scaled = xmax_limit_sec * current_scale
            if xmax_sec_global is None and t_scaled:
                 xmax_limit_scaled = max(xmax_limit_scaled, t_scaled[-1])
                 if xmax_limit_scaled > 0:
                      xmax_display = xmax_limit_scaled * 1.02
                 else:
                      xmax_display = 1
            else:
                 xmax_display = xmax_limit_scaled
            if xmax_display > 0:
                xmin_plot = 0
                ax.set_xlim(xmin_plot, xmax_display)
            elif t_scaled:
                ax.set_xlim(-0.1, 0.1)
            else:
                ax.set_xlim(0, 1)
            if tick_step_sec is not None:
                base_step_scaled = tick_step_sec * current_scale
                if base_step_scaled > 1e-12:
                    locator = ticker.MultipleLocator(base=base_step_scaled)
                else:
                    print(f"Warning: Шаг тиков ({fmt(tick_step_sec)}) слишком мал для масштаба '{current_unit}' на графике '{s.Name}'. Используется auto.")
                    locator = ticker.MaxNLocator(nbins='auto', prune='both', integer=False)
            else:
                locator = ticker.MaxNLocator(nbins='auto', prune='both', integer=False)
            ax.xaxis.set_major_locator(locator)
            ax.xaxis.set_major_formatter(unit_formatter(current_unit))
            ax.grid(True, ls=':', lw=0.6, color='lightgrey')
            if i != n_signals - 1:
                ax.set_xticklabels([])
            else:
                ax.set_xlabel(f'Время ({current_unit})', fontsize=9)
        try:
            self.fig.set_layout_engine('constrained', h_pad=0.04, w_pad=0.02)
        except Exception:
            try:
                 self.fig.tight_layout(h_pad=0.6)
            except Exception as e:
                 print(f"Layout adjustment failed: {e}")
        self.canvas.draw_idle()

# ───── Запуск приложения ─────
def main():
    try:
        root = tk.Tk()
        app = PulseApp(root)
        root.mainloop()
    except Exception as e:
        import traceback
        messagebox.showerror("Критическая ошибка", f"Произошла ошибка при запуске:\n{e}\n\n{traceback.format_exc()}")

if __name__ == '__main__':
    main()