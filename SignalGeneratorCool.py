#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Генератор импульсов v3‑u5 (модифицирован)
— каждый сигнал рисуется в одном окне, друг‑под‑другом
— тики оси X выводят число + единицу измерения (ns, µs…)
— добавлена настройка шага тиков оси X (e.g., '10ns', '0.5us')
— возможность загрузки списка сигналов из файла (форматы PULSE и PWL)
— можно менять порядок сигналов перетаскиванием мышью или Ctrl+↑/↓
— добавлена возможность выбора режима ввода параметров: либо T_HIGH и T_LOW, либо T_PULSE_WIDTH и T_PERIOD
— ДОБАВЛЕНО: Таблица для редактирования точек выбранного сигнала
— ДОБАВЛЕНО: Кнопка для обновления графика по данным из таблицы
— ДОБАВЛЕНО: Скроллбар для таблицы точек
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
import csv
try:
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter
    from openpyxl.styles import Font
    XLSX_SUPPORT = True
except ImportError:
    XLSX_SUPPORT = False

# ───── Вспомогательные функции времени (ОБНОВЛЕНО) ─────

# Словарь для ПАРСИНГА (регистронезависимый)
# Ключи: 'f', 'p', 'n', 'u', 'm', 'k', 'meg', 'g', ''
# Добавим поддержку 'µ' как 'u'
_PARSE_UNITS = {'f': 1e-15, 'p': 1e-12, 'n': 1e-9, 'u': 1e-6, 'µ': 1e-6, 'm': 1e-3,
                'k': 1e3, 'meg': 1e6, 'g': 1e9, '': 1}
# Регулярное выражение для парсинга: число, опциональные буквы, опционально 's'
# Позволяет вводить '10n', '5 u', '0.1ms', '100ps', '1k', '2meg', '3gs', '10'
# Буквы приводятся к нижнему регистру для поиска в _PARSE_UNITS
_TIME_RE = re.compile(r'^\s*([+-]?[0-9.]+(?:e[+-]?[0-9]+)?)\s*([a-zµ]*?)s?\s*$', re.IGNORECASE)

def parse_time(s: str) -> float:
    """
    Преобразует строку (e.g., '10n', '5u', '0.1m', '100p', '1k', '2meg', '5') в секунды.
    Регистронезависимо. Распознает f, p, n, u, µ, m, k, meg, g. Число без единицы - секунды.
    """
    s_orig = str(s).strip()
    if not s_orig:
        raise ValueError("Пустая строка времени")

    m = _TIME_RE.fullmatch(s_orig)
    if not m:
        # Если regex не сработал, попробуем просто как float (для чисел без единиц)
        try:
            v = float(s_orig)
            # Время не может быть отрицательным, но для промежуточных расчетов или напряжения - может
            # Оставим проверку на отрицательность там, где это семантически нужно (TD, TR и т.д.)
            # if v < 0: raise ValueError("Время не может быть отрицательным") # Убрали глобальную проверку
            return v
        except ValueError:
            raise ValueError(f'Неверный формат времени: "{s_orig}"')

    v_str, u_str = m.groups()
    unit_lower = u_str.lower()

    try:
        v = float(v_str)
    except ValueError:
        raise ValueError(f'Неверное числовое значение: "{v_str}" в "{s_orig}"')

    # Подбираем множитель из словаря
    multiplier = None
    if unit_lower in _PARSE_UNITS:
        multiplier = _PARSE_UNITS[unit_lower]
    elif unit_lower == 'mega': # Альтернативное написание
        multiplier = _PARSE_UNITS['meg']
    elif unit_lower == 'giga': # Альтернативное написание
        multiplier = _PARSE_UNITS['g']
    elif not unit_lower: # Пустая единица
        multiplier = _PARSE_UNITS['']
    else:
        raise ValueError(f'Неизвестная единица измерения: "{u_str}" в "{s_orig}"')

    result = v * multiplier
    # Проверка на отрицательность должна быть в вызывающем коде, где это уместно
    # if result < 0:
    #     # Проверим контекст TD, TR, TF, TH, TL, N - они не могут быть < 0
    #     # V0, V1 могут быть отрицательными
    #     # Лучше проверять в _read_signal_data
    #     pass
    return result

# Словарь для ФОРМАТИРОВАНИЯ (используем 'u', 'M', 'G')
_FMT_UNITS_INV = {1e-15: 'f', 1e-12: 'p', 1e-9: 'n', 1e-6: 'u', 1e-3: 'm',
                  1: 's', 1e3: 'k', 1e6: 'M', 1e9: 'G'}
# Сортированные ключи для поиска диапазона
_FMT_THRESHOLDS = sorted(_FMT_UNITS_INV.keys())

def fmt(sec: float) -> str:
    """
    Форматирует время (секунды) в строку с однобуквенной единицей измерения (f, p, n, u, m, s, k, M, G).
    """
    if sec == 0:
        return '0s'
    a = abs(sec)
    sign = '-' if sec < 0 else '' # Сохраняем знак

    # Ищем подходящий префикс
    best_unit = 's' # По умолчанию
    best_mult = 1.0

    if a >= 1:
        if a >= 1e9: best_unit, best_mult = 'G', 1e-9
        elif a >= 1e6: best_unit, best_mult = 'M', 1e-6
        elif a >= 1e3: best_unit, best_mult = 'k', 1e-3
        else: best_unit, best_mult = 's', 1.0
    elif a > 0:
        if a < 1e-15: # Очень маленькие числа -> научная нотация
             return f'{sec:.3e}s'
        elif a < 1e-12: best_unit, best_mult = 'f', 1e15
        elif a < 1e-9: best_unit, best_mult = 'p', 1e12
        elif a < 1e-6: best_unit, best_mult = 'n', 1e9
        elif a < 1e-3: best_unit, best_mult = 'u', 1e6
        else: best_unit, best_mult = 'm', 1e3
    else: # Отрицательные, но не 0
        # Повторяем логику для модуля, знак добавим в конце
        a_abs = abs(a)
        if a_abs >= 1e9: best_unit, best_mult = 'G', 1e-9
        elif a_abs >= 1e6: best_unit, best_mult = 'M', 1e-6
        elif a_abs >= 1e3: best_unit, best_mult = 'k', 1e-3
        elif a_abs >= 1: best_unit, best_mult = 's', 1.0
        elif a_abs < 1e-15: return f'{sec:.3e}s'
        elif a_abs < 1e-12: best_unit, best_mult = 'f', 1e15
        elif a_abs < 1e-9: best_unit, best_mult = 'p', 1e12
        elif a_abs < 1e-6: best_unit, best_mult = 'n', 1e9
        elif a_abs < 1e-3: best_unit, best_mult = 'u', 1e6
        else: best_unit, best_mult = 'm', 1e3

    # Форматируем число с 4 значащими цифрами
    val_scaled = a * best_mult
    formatted_val = f"{val_scaled:.4g}"

    # Убираем лишние нули и точку для целых чисел в результате форматирования
    if '.' in formatted_val:
        formatted_val = formatted_val.rstrip('0').rstrip('.')

    return f"{sign}{formatted_val}{best_unit}"

def autoscale(total: float) -> tuple[float, str]:
    """
    Определяет множитель и единицу измерения (f, p, n, u, m, s) для оси X.
    Использует секунды для значений >= 1.
    """
    if total <= 0: return 1, 's' # Масштаб 1, единица 's'

    # Используем абсолютное значение для определения масштаба
    a = abs(total)

    if a >= 1: return 1, 's'      # Секунды
    if a >= 1e-3: return 1e3, 'm'      # Миллисекунды
    if a >= 1e-6: return 1e6, 'u'   # Микросекунды
    if a >= 1e-9: return 1e9, 'n'   # Наносекунды
    if a >= 1e-12: return 1e12, 'p'  # Пикосекунды
    # Порог для фемто? или научная нотация?
    # Если total очень мало, например 1e-16
    if a >= 1e-15: return 1e15, 'f'  # Фемтосекунды
    # Если еще меньше, возможно, стоит использовать пико или нано как минимум?
    # Или оставить секунды с научной нотацией? Autoscale обычно для осей...
    # Matplotlib сам справится с малыми числами. Вернем 'f' как самый малый.
    return 1e15, 'f' # Возвращаем фемто для очень малых

def unit_formatter(unit: str):
    """Возвращает форматер оси X для Matplotlib с однобуквенной единицей."""
    # unit теперь это 'f', 'p', 'n', 'u', 'm', 's'.
    unit_str = unit if unit != 's' else ' s' # Добавляем пробел только перед 's'
    # Форматтер для Matplotlib. '{x:g}' автоматически выбирает формат числа.
    return ticker.FuncFormatter(lambda x, pos: f'{x:g}{unit_str}')

# ───── Data class сигнала ─────
@dataclass
class Signal:
    # Основные параметры PULSE
    V0: float; V1: float
    TD: float; TR: float; TF: float; TH: float; TL: float
    N: int;   Name: str
    # Расчетные поля
    tp: float = field(init=False)
    total_time: float = field(init=False)
    scale: float = field(init=False); unit: str = field(init=False)
    # Хранилище для точек, если сигнал был изменен через таблицу
    # Если None, используются параметры PULSE. Иначе - эти точки.
    pwl_points: tuple[list[float], list[float]] | None = None

    def __post_init__(self):
        self.update()

    def update(self):
        """Пересчитывает дополнительные параметры сигнала. Сбрасывает pwl_points."""
        self.TR = max(1e-15, self.TR) # Избегаем нулевых времен для корректного расчета PW
        self.TF = max(1e-15, self.TF)
        self.TH = max(0, self.TH)
        self.TL = max(0, self.TL)
        self.TD = max(0, self.TD)
        self.N = max(0, self.N)
        self.tp = self.TR + self.TH + self.TF + self.TL
        # Убедимся, что tp не ноль, если N>0, чтобы избежать деления на ноль или зависаний
        if self.N > 0 and self.tp <= 1e-15:
            print(f"Warning: Signal '{self.Name}' has N > 0 but calculated period (tp) is near zero. Setting N=0.")
            # Можно установить N=0 или задать минимальный tp
            self.tp = 1e-9 # Например, 1 нс по умолчанию, если все времена были 0
            # self.N = 0 # Альтернатива - обнулить N

        self.total_time = self.TD if self.N == 0 else self.TD + self.N * self.tp
        self.scale, self.unit = autoscale(self.total_time if self.total_time > 0 else 1e-9) # Масштаб по умолчанию если время 0
        # Сбрасываем PWL представление при обновлении параметров
        self.pwl_points = None

    def set_pwl_points(self, times: list[float], voltages: list[float]):
        """Устанавливает точки PWL и обновляет total_time."""
        if not times:
            self.pwl_points = None
            self.total_time = 0
        else:
            # Убедимся, что время монотонно возрастает
            valid_times = [times[0]]
            valid_voltages = [voltages[0]]
            for i in range(1, len(times)):
                if times[i] > valid_times[-1]:
                    valid_times.append(times[i])
                    valid_voltages.append(voltages[i])
                elif times[i] == valid_times[-1]:
                    # Если время то же, обновляем напряжение последней точки
                    valid_voltages[-1] = voltages[i]
                # else: Игнорируем точки с меньшим временем (ошибка данных)

            self.pwl_points = (valid_times, valid_voltages)
            self.total_time = valid_times[-1] if valid_times else 0
        self.scale, self.unit = autoscale(self.total_time if self.total_time > 0 else 1e-9)

    def get_waveform_points(self, xmax: float | None = None, force_pulse: bool = False) -> tuple[list[float], list[float]]:
        """
        Генерирует точки (t, v) для построения графика сигнала.
        Использует self.pwl_points если они заданы И force_pulse=False.
        Иначе генерирует из параметров PULSE.
        Если задан xmax, сигнал продолжается до этого значения.
        """
        # --- Выбор источника точек ---
        use_pwl = self.pwl_points is not None and not force_pulse

        if use_pwl:
            # Используем сохраненные точки PWL
            times, voltages = self.pwl_points
            # Копируем, чтобы не изменить оригинал при добавлении xmax
            times = list(times)
            voltages = list(voltages)
            theoretical_end = times[-1] if times else 0
            # print(f"DEBUG: Signal '{self.Name}' using PWL points for get_waveform_points.") # Отладочный вывод
        else:
            # Генерируем точки из параметров PULSE
            # print(f"DEBUG: Signal '{self.Name}' using PULSE params for get_waveform_points (force_pulse={force_pulse}).") # Отладочный вывод
            times: list[float] = []
            voltages: list[float] = []
            t_cur = 0.0

            # Начальная точка
            times.append(0.0)
            voltages.append(self.V0)

            # Задержка (Delay)
            if self.TD > 0:
                t_cur = self.TD # Время конца задержки
                # Проверим, что не добавляем точку с тем же временем, если TD=0
                if not times or abs(times[-1] - t_cur) > 1e-15:
                    times.append(t_cur)
                    voltages.append(self.V0)
                else: # Если TD=0, просто обновим напряжение начальной точки, если нужно (хотя V0 уже там)
                     if voltages: voltages[-1] = self.V0


            # Импульсы
            if self.N > 0 and self.tp > 1e-15: # Проверяем, что период не нулевой
                for i in range(self.N):
                    # Rise time
                    t_rise_end = t_cur + self.TR
                    if self.TR > 1e-15: # Добавляем точку только если время > 0
                        times.append(t_rise_end)
                        voltages.append(self.V1)
                    t_cur = t_rise_end

                    # High time
                    t_high_end = t_cur + self.TH
                    if self.TH > 1e-15:
                        # Добавляем точку только если время изменилось
                        if not times or abs(times[-1] - t_high_end) > 1e-15:
                            times.append(t_high_end)
                            voltages.append(self.V1)
                        elif voltages: # Если время то же, обновляем напряжение
                            voltages[-1] = self.V1
                    t_cur = t_high_end

                    # Fall time
                    t_fall_end = t_cur + self.TF
                    if self.TF > 1e-15:
                        times.append(t_fall_end)
                        voltages.append(self.V0)
                    t_cur = t_fall_end

                    # Low time
                    t_low_end = t_cur + self.TL
                    if self.TL > 1e-15:
                         # Добавляем точку только если время изменилось
                        if not times or abs(times[-1] - t_low_end) > 1e-15:
                            times.append(t_low_end)
                            voltages.append(self.V0)
                        elif voltages: # Если время то же, обновляем напряжение
                             voltages[-1] = self.V0
                    t_cur = t_low_end # Время на конец периода i

            # Рассчитаем теоретическое время конца последнего импульса/задержки
            theoretical_end = self.TD if self.N == 0 else self.TD + self.N * self.tp

            # Добавляем конечную точку, если она отличается от последней добавленной
            if not times or abs(times[-1] - theoretical_end) > 1e-12:
                 # Конечный уровень после N импульсов или задержки - V0
                 times.append(theoretical_end)
                 voltages.append(self.V0)
            elif voltages: # Если время совпадает, убедимся, что напряжение = V0
                voltages[-1] = self.V0


        # --- Обработка xmax и очистка (общая для PWL и PULSE) ---

        # Обработка xmax: продление сигнала до xmax, если необходимо
        if xmax is not None and theoretical_end < xmax:
            last_v = voltages[-1] if voltages else self.V0 # Напряжение в theoretical_end
            # Если последняя точка уже на theoretical_end, просто добавляем xmax
            if times and abs(times[-1] - theoretical_end) < 1e-12 :
                 # Проверим, нужно ли вообще продлевать (xmax может быть равен theoretical_end)
                 if abs(xmax - theoretical_end) > 1e-12:
                     times.append(xmax)
                     voltages.append(last_v)
            # Если последняя точка не на theoretical_end (например, из-за нулевых интервалов)
            # Или если xmax больше theoretical_end, добавляем обе точки
            elif abs(xmax - theoretical_end) > 1e-12:
                 # Добавим точку theoretical_end, если ее еще нет или она не последняя
                 if not times or abs(times[-1] - theoretical_end) > 1e-12:
                     times.append(theoretical_end)
                     voltages.append(last_v)
                 elif voltages: # Если последняя точка на theoretical_end, убедимся в правильном напряжении
                      voltages[-1] = last_v
                 # Добавим точку xmax
                 times.append(xmax)
                 voltages.append(last_v)

        # Очистка от дубликатов времени (могут возникнуть из-за нулевых интервалов или PWL)
        clean_times = []
        clean_voltages = []
        if times:
            last_t = -1.0 # Гарантированно меньше первого времени (>=0)
            for t, v in zip(times, voltages):
                # Добавляем точку только если время изменилось
                if abs(t - last_t) > 1e-15: # Используем малый допуск
                    clean_times.append(t)
                    clean_voltages.append(v)
                    last_t = t
                else:
                    # Если время то же, обновляем напряжение последней точки
                    if clean_voltages:
                        clean_voltages[-1] = v

        # Убедимся, что есть хотя бы начальная точка 0, V0, если генерация дала пустой список
        if not clean_times:
             clean_times.append(0.0)
             clean_voltages.append(self.V0)
             if xmax is not None and xmax > 0:
                 # Добавим точку xmax, если она отличается от 0
                 if abs(xmax - 0.0) > 1e-15:
                     clean_times.append(xmax)
                     clean_voltages.append(self.V0)

        return clean_times, clean_voltages


# ───── Главное приложение ─────
class PulseApp(ttk.Frame):
    FIELDS = (('V0','Ур0'), ('V1','Ур1'), ('TD','Delay'), ('TR','Rise'),
              ('TF','Fall'), ('TH','High'), ('TL','Low'), ('N','Cnt'), ('Name','Имя'))

    def __init__(self, master: tk.Tk):
        super().__init__(master)
        self.pack(fill='both', expand=True)
        master.title('Impulse generator v3‑u5 (с ред. таблицы)')
        master.minsize(850, 650) # Увеличим мин. размер
        self.signals: list[Signal] = []
        self._drag_start_index = None
        self.mode = "high-low"
        self._editing_cell_entry = None # Виджет для редактирования ячейки Treeview
        self._style()
        self._layout()
        self._mpl()
        # Флаг, указывающий, что данные для выбранного сигнала взяты из таблицы
        self.updated_from_table_index = None

    def _style(self):
        st = ttk.Style()
        st.theme_use('clam')
        st.configure('TButton', font=('Segoe UI', 10))
        st.configure('TLabel', font=('Segoe UI', 10))
        st.configure('TEntry', font=('Segoe UI', 10))
        st.configure('TLabelframe.Label', font=('Segoe UI', 10, 'bold'))
        # Стиль для Treeview
        st.configure("Treeview.Heading", font=('Segoe UI', 10, 'bold'))
        st.configure("Treeview", font=('Segoe UI', 9), rowheight=22) # Немного уменьшим шрифт строк

    def _layout(self):
        main_paned = ttk.PanedWindow(self, orient='horizontal')
        main_paned.pack(fill='both', expand=True, padx=5, pady=(5, 0))

        # ─── Левая панель (Список сигналов + Таблица точек) ───
        left_panel = ttk.Frame(main_paned, padding=0)
        main_paned.add(left_panel, weight=1) # Меньший вес для левой панели

        # Верхняя часть левой панели: Список сигналов
        list_frame = ttk.Frame(left_panel)
        list_frame.pack(fill='both', expand=True, pady=(0, 5)) # Занимает доступное место

        self.lb = tk.Listbox(list_frame, exportselection=False, font=('Segoe UI', 10), height=8) # Уменьшим высоту списка
        self.lb.pack(side='top', fill='both', expand=True)
        self.lb.bind('<<ListboxSelect>>', self.on_select)
        self.lb.bind('<ButtonPress-1>', self.on_lb_button_press)
        self.lb.bind('<B1-Motion>', self.on_lb_motion)
        self.lb.bind('<Control-Up>', self.move_item_up)
        self.lb.bind('<Control-Down>', self.move_item_down)

        list_buttons_frame = ttk.Frame(list_frame)
        list_buttons_frame.pack(fill='x', pady=(5, 0))
        btn_configs = (('Load', self.load), ('Add', self.add),
                       ('Del', self.delete), ('Export', self.export))
        for i, (text, cmd) in enumerate(btn_configs):
            btn = ttk.Button(list_buttons_frame, text=text, command=cmd)
            btn.pack(side='left', expand=True, fill='x', padx=(0, 2) if i < len(btn_configs)-1 else 0)

        # Разделитель
        ttk.Separator(left_panel, orient='horizontal').pack(fill='x', pady=5)

        # Нижняя часть левой панели: Таблица точек
        table_frame = ttk.LabelFrame(left_panel, text="Точки выбранного сигнала", padding=5)
        table_frame.pack(fill='both', expand=True, pady=(0, 5)) # Занимает оставшееся место

        self.points_table = ttk.Treeview(table_frame, columns=('time', 'voltage'), show='headings', height=6)
        self.points_table.heading('time', text='Время')
        self.points_table.heading('voltage', text='Напряжение')
        self.points_table.column('time', width=100, anchor='e')
        self.points_table.column('voltage', width=80, anchor='e')

        # Скроллбар для таблицы
        points_scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.points_table.yview)
        self.points_table.configure(yscrollcommand=points_scrollbar.set)

        points_scrollbar.pack(side='right', fill='y')
        self.points_table.pack(side='left', fill='both', expand=True)

        # Привязка двойного клика для редактирования
        self.points_table.bind('<Double-1>', self._on_tree_double_click)

        # Кнопка обновления графика по таблице
        self.update_from_table_btn = ttk.Button(left_panel, text='Обновить график по данным таблицы',
                                                command=self._update_graph_from_table, state='disabled')
        self.update_from_table_btn.pack(fill='x', pady=(0, 5))


        # ─── Правая панель (График) ───
        self.plot_fr = ttk.Frame(main_paned, padding=0)
        main_paned.add(self.plot_fr, weight=4) # Больший вес для графика

        # ─── Нижняя панель (Параметры и управление) ───
        editor_frame = ttk.LabelFrame(self, text='Параметры сигнала и графика', padding=10)
        editor_frame.pack(fill='x', padx=5, pady=5)

        # Режим ввода
        mode_frame = ttk.Frame(editor_frame)
        mode_frame.grid(row=0, column=0, columnspan=4, sticky='ew', pady=(0, 10))
        ttk.Label(mode_frame, text="Режим параметров:").pack(side='left')
        self.mode_var = tk.StringVar(value="T_HIGH/T_LOW")
        self.mode_combobox = ttk.Combobox(mode_frame, textvariable=self.mode_var, state="readonly",
                                          values=["T_HIGH/T_LOW", "T_PULSE_WIDTH/T_PERIOD"])
        self.mode_combobox.pack(side='left', padx=5)
        self.mode_combobox.bind("<<ComboboxSelected>>", self.on_mode_change)

        # Поля параметров сигнала
        self.ent: dict[str, ttk.Entry] = {}
        self.param_labels: dict[str, ttk.Label] = {}
        col_param = 0
        for i, (k, lbl) in enumerate(self.FIELDS):
            actual_lbl = lbl
            if k == 'TH': actual_lbl = "High" if self.mode == "high-low" else "PW"
            elif k == 'TL': actual_lbl = "Low" if self.mode == "high-low" else "Period"
            label_widget = ttk.Label(editor_frame, text=actual_lbl+':')
            label_widget.grid(row=i+1, column=col_param, sticky='e', padx=(0,5), pady=2)
            self.param_labels[k] = label_widget
            entry_widget = ttk.Entry(editor_frame, width=12, font=('Segoe UI', 10))
            entry_widget.grid(row=i+1, column=col_param+1, sticky='ew', padx=4, pady=1)
            self.ent[k] = entry_widget

        # Параметры графика
        col_graph = 2
        ttk.Label(editor_frame, text='X‑max:').grid(row=1, column=col_graph, sticky='e', padx=(15,5), pady=2)
        self.xmax_var = tk.StringVar(value='auto')
        ttk.Entry(editor_frame, textvariable=self.xmax_var, width=10, font=('Segoe UI', 10)).grid(row=1, column=col_graph+1, sticky='ew', padx=4, pady=1)

        ttk.Label(editor_frame, text='Шаг тиков X:').grid(row=2, column=col_graph, sticky='e', padx=(15,5), pady=2)
        self.xtick_step_var = tk.StringVar(value='auto')
        self.xtick_step_entry = ttk.Entry(editor_frame, textvariable=self.xtick_step_var, width=10, font=('Segoe UI', 10))
        self.xtick_step_entry.grid(row=2, column=col_graph+1, sticky='ew', padx=4, pady=1)

        # Кнопка Применить / Обновить график (работает с параметрами)
        apply_btn = ttk.Button(editor_frame, text='Применить параметры / Обновить график', command=self.apply_and_draw)
        apply_btn.grid(row=len(self.FIELDS)+1, column=0, columnspan=4, pady=(10, 0), sticky='ew')
        editor_frame.columnconfigure(col_param+1, weight=1)
        editor_frame.columnconfigure(col_graph+1, weight=1)

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

    def on_mode_change(self, event):
        mode_sel = self.mode_var.get()
        new_mode = "pw-period" if mode_sel == "T_PULSE_WIDTH/T_PERIOD" else "high-low"
        if new_mode != self.mode:
            self.mode = new_mode
            # Обновляем метки
            if 'TH' in self.param_labels:
                new_lbl_th = "High" if self.mode == "high-low" else "PW"
                self.param_labels['TH'].config(text=new_lbl_th + ':')
            if 'TL' in self.param_labels:
                new_lbl_tl = "Low" if self.mode == "high-low" else "Period"
                self.param_labels['TL'].config(text=new_lbl_tl + ':')
            # Обновляем значения в полях для текущего выбранного сигнала
            idx = self._get_selected_index()
            if idx is not None and 0 <= idx < len(self.signals):
                self._update_entries(self.signals[idx])

    def _read_signal_data(self) -> Signal:
        """Читает данные из полей ввода параметров."""
        v = {k: self.ent[k].get().strip() for k, _ in self.FIELDS}
        try:
            name = v['Name'] if v['Name'] else f'Signal {len(self.signals)+1}'
            v0 = float(v['V0'] or 0)
            v1 = float(v['V1'] or 1)
            td = parse_time(v['TD'] or "0")
            tr = parse_time(v['TR'] or "1n") # Используем parse_time для всех времен
            tf = parse_time(v['TF'] or "1n")

            if self.mode == "high-low":
                th = parse_time(v['TH'] or "1u")
                tl = parse_time(v['TL'] or "1u")
            else: # Режим T_PULSE_WIDTH/T_PERIOD
                pulse_width_str = v['TH'] or "1u"
                period_str = v['TL'] or "1u"
                pulse_width = parse_time(pulse_width_str)
                period = parse_time(period_str)

                # Проверки для режима PW/Period
                min_pw = tr + tf
                if pulse_width < min_pw:
                    raise ValueError(f"T_PULSE_WIDTH ({fmt(pulse_width)}) должен быть >= TR+TF ({fmt(min_pw)})")
                if period < pulse_width:
                     raise ValueError(f"T_PERIOD ({fmt(period)}) должен быть >= T_PULSE_WIDTH ({fmt(pulse_width)})")

                # Рассчитываем TH и TL для внутреннего хранения
                th = pulse_width - tr - tf
                tl = period - pulse_width

            n = int(v['N'] or 1)
            if n < 0: raise ValueError("Число импульсов (Cnt) не может быть отрицательным")

            return Signal(V0=v0, V1=v1, TD=td, TR=tr, TF=tf, TH=th, TL=tl, N=n, Name=name)

        except ValueError as e:
            raise ValueError(f"Ошибка в параметрах сигнала: {e}")
        except Exception as e:
            raise ValueError(f"Неожиданная ошибка чтения параметров: {e}")

    def _get_selected_index(self):
        s = self.lb.curselection()
        return int(s[0]) if s else None

    def move_in_list(self, from_index: int, to_index: int):
        if from_index == to_index: return
        sig = self.signals.pop(from_index)
        self.signals.insert(to_index, sig)
        label = self.lb.get(from_index)
        self.lb.delete(from_index)
        self.lb.insert(to_index, label)
        self.lb.select_clear(0, 'end')
        self.lb.selection_set(to_index)
        self.lb.activate(to_index)
        self.draw() # Перерисовываем, так как порядок изменился

    def on_lb_button_press(self, event):
        self._drag_start_index = self.lb.nearest(event.y)

    def on_lb_motion(self, event):
        cur_index = self.lb.nearest(event.y)
        if cur_index != self._drag_start_index and self._drag_start_index is not None:
             # Проверим, что индексы валидны
             size = self.lb.size()
             if 0 <= self._drag_start_index < size and 0 <= cur_index < size:
                 self.move_in_list(self._drag_start_index, cur_index)
                 self._drag_start_index = cur_index # Обновляем стартовый индекс для продолжения перетаскивания

    def move_item_up(self, event):
        i = self._get_selected_index()
        if i is not None and i > 0:
            self.move_in_list(i, i - 1)
        return "break" # Предотвращаем стандартную обработку

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
        # Сразу обновим таблицу и график
        self.on_select() # Это вызовет _populate_points_table
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
                 # Сбрасываем флаг, если удалили редактируемый из таблицы сигнал
                if self.updated_from_table_index == i:
                    self.updated_from_table_index = None

                if self.lb.size() > 0:
                    new_selection = min(i, self.lb.size() - 1)
                    self.lb.selection_set(new_selection)
                    self.lb.activate(new_selection)
                    self.on_select() # Обновит панель и таблицу для нового выбора
                else:
                    self._clear_entries()
                    self._clear_points_table() # Очистить таблицу точек
                    self.update_from_table_btn.config(state='disabled')
                self.draw() # Перерисовать график
        else:
             messagebox.showerror("Ошибка", "Не удалось удалить сигнал: неверный индекс.")

    def apply_and_draw(self):
        """Применяет параметры из полей ввода к выбранному сигналу и перерисовывает."""
        i = self._get_selected_index()
        if i is not None:
            if 0 <= i < len(self.signals):
                try:
                    original_name = self.signals[i].Name
                    updated_signal_params = self._read_signal_data() # Читаем параметры из полей
                    if not updated_signal_params.Name:
                        updated_signal_params.Name = original_name

                    # Обновляем объект сигнала, используя новые параметры
                    # Это автоматически вызовет update() и сбросит pwl_points
                    self.signals[i] = updated_signal_params

                    # Если имя изменилось, обновляем Listbox
                    if self.lb.get(i) != updated_signal_params.Name:
                        self.lb.delete(i)
                        self.lb.insert(i, updated_signal_params.Name)
                        self.lb.select_set(i)

                    # Сбрасываем флаг редактирования из таблицы, т.к. применили параметры
                    self.updated_from_table_index = None
                    # Обновляем таблицу точек, т.к. параметры изменились
                    self._populate_points_table(self.signals[i])

                except ValueError as e:
                    messagebox.showerror('Ошибка ввода', str(e))
                    return # Не перерисовываем если ошибка
                except Exception as e:
                    messagebox.showerror('Ошибка применения', f"Не удалось применить изменения: {e}")
                    return # Не перерисовываем если ошибка
        # Перерисовываем все графики
        self.draw()

    # --- Методы для работы с таблицей точек ---

    def _clear_points_table(self):
        """Очищает таблицу точек."""
        if self._editing_cell_entry: # Уничтожаем виджет редактирования, если он есть
             self._editing_cell_entry.destroy()
             self._editing_cell_entry = None
        for item in self.points_table.get_children():
            self.points_table.delete(item)

    def _populate_points_table(self, signal: Signal):
        """Заполняет таблицу точек данными из сигнала."""
        self._clear_points_table()
        # Получаем точки (либо из PWL, либо генерируем из PULSE)
        times, voltages = signal.get_waveform_points() # Не используем xmax для таблицы

        if not times:
            self.update_from_table_btn.config(state='disabled')
            return

        for i, (t, v) in enumerate(zip(times, voltages)):
            # Форматируем время для отображения
            time_str = fmt(t)
            # Форматируем напряжение (используем 'g' для компактности)
            voltage_str = f"{v:g}"
            # Добавляем строку в Treeview. item id будет использоваться для доступа
            self.points_table.insert('', 'end', iid=str(i), values=(time_str, voltage_str))

        self.update_from_table_btn.config(state='normal')


    def _on_tree_double_click(self, event):
        """Обработчик двойного клика по ячейке таблицы для начала редактирования."""
        # Уничтожаем предыдущий виджет редактирования, если он был
        if self._editing_cell_entry:
            self._editing_cell_entry.destroy()
            self._editing_cell_entry = None

        region = self.points_table.identify_region(event.x, event.y)
        if region != "cell":
            return # Кликнули не по ячейке

        item_id = self.points_table.identify_row(event.y)
        column_id = self.points_table.identify_column(event.x)
        column_index = int(column_id.replace('#', '')) - 1 # 0 для времени, 1 для напряжения

        if not item_id or column_index < 0 or column_index > 1:
            return # Не попали или не та колонка

        # Получаем геометрию ячейки
        x, y, width, height = self.points_table.bbox(item_id, column_id)

        # Получаем текущее значение
        current_values = self.points_table.item(item_id, 'values')
        value = current_values[column_index]

        # Создаем Entry поверх ячейки
        entry = ttk.Entry(self.points_table, font=('Segoe UI', 9))
        entry.place(x=x, y=y, width=width, height=height)
        entry.insert(0, value)
        entry.select_range(0, 'end')
        entry.focus_set()
        self._editing_cell_entry = entry # Сохраняем ссылку на виджет

        # Сохраняем информацию о редактируемой ячейке
        entry.editing_info = {'item_id': item_id, 'column_index': column_index}

        # Привязываем события для завершения редактирования
        entry.bind("<Return>", self._on_edit_save)
        entry.bind("<KP_Enter>", self._on_edit_save) # Enter на цифровой клавиатуре
        entry.bind("<FocusOut>", self._on_edit_save)
        entry.bind("<Escape>", self._on_edit_cancel)

    def _on_edit_save(self, event):
        """Сохраняет измененное значение из Entry в Treeview."""
        entry = event.widget
        if not hasattr(entry, 'editing_info'): return # Не наш виджет

        new_value_str = entry.get()
        info = entry.editing_info
        item_id = info['item_id']
        col_index = info['column_index']

        # Получаем текущие значения строки
        current_values = list(self.points_table.item(item_id, 'values'))

        # Пытаемся валидировать и обновить значение
        try:
            if col_index == 0: # Время
                # Пробуем парсить время, допускаем и просто числа (секунды)
                parsed_time = parse_time(new_value_str)
                formatted_time = fmt(parsed_time) # Переформатируем для единообразия
                current_values[col_index] = formatted_time
            else: # Напряжение
                parsed_voltage = float(new_value_str)
                current_values[col_index] = f"{parsed_voltage:g}" # Сохраняем как строку

            # Обновляем значения в Treeview
            self.points_table.item(item_id, values=tuple(current_values))

        except ValueError as e:
            messagebox.showerror("Ошибка ввода", f"Неверное значение '{new_value_str}':\n{e}", parent=self.master)
            # Не закрываем редактор при ошибке, даем исправить
            entry.focus_set() # Возвращаем фокус
            return # Прерываем сохранение

        # Уничтожаем Entry
        entry.destroy()
        self._editing_cell_entry = None
        # Возможно, стоит вызвать _update_graph_from_table() сразу?
        # Или оставить это на кнопку "Обновить график по данным таблицы"

    def _on_edit_cancel(self, event):
        """Отменяет редактирование и уничтожает Entry."""
        if event.widget == self._editing_cell_entry:
            event.widget.destroy()
            self._editing_cell_entry = None

    def _update_graph_from_table(self):
        """Читает данные из таблицы, обновляет PWL точки сигнала и перерисовывает график."""
        idx = self._get_selected_index()
        if idx is None or not (0 <= idx < len(self.signals)):
             messagebox.showwarning("Нет выбора", "Выберите сигнал, для которого нужно обновить график по таблице.")
             return

        signal = self.signals[idx]
        new_times = []
        new_voltages = []
        row_num = 0

        # Проходим по всем строкам таблицы
        item_ids = self.points_table.get_children()
        if not item_ids:
             messagebox.showinfo("Таблица пуста", "Нет точек для обновления.")
             return

        for item_id in item_ids:
            row_num += 1
            values = self.points_table.item(item_id, 'values')
            time_str = values[0]
            voltage_str = values[1]

            try:
                # Парсим время
                t = parse_time(time_str)
                # Парсим напряжение
                v = float(voltage_str)

                # Проверка монотонности времени (важно!)
                if new_times and t <= new_times[-1]:
                     # Нестрогое неравенство, т.к. две точки могут быть в одно время (вертикальный фронт)
                     # Но для PWL лучше избегать строго одинакового времени, если только это не последняя точка обновления напряжения
                    if t < new_times[-1]:
                         raise ValueError(f"Время должно монотонно возрастать. Нарушение в строке {row_num} ({fmt(t)} <= {fmt(new_times[-1])}).")
                    # Если время то же самое, обновляем напряжение последней добавленной точки
                    elif new_voltages:
                        new_voltages[-1] = v
                        continue # Не добавляем новую точку, только обновляем напряжение

                new_times.append(t)
                new_voltages.append(v)

            except ValueError as e:
                messagebox.showerror("Ошибка данных в таблице", f"Ошибка в строке {row_num}:\n{e}")
                # Выделяем ошибочную строку в таблице
                self.points_table.selection_set(item_id)
                self.points_table.focus(item_id)
                self.points_table.see(item_id)
                return # Прерываем обновление

        # Если все успешно прочитано, обновляем PWL данные сигнала
        signal.set_pwl_points(new_times, new_voltages)

        # Устанавливаем флаг, что этот сигнал теперь определяется таблицей
        self.updated_from_table_index = idx

        # Перерисовываем график
        self.draw()
        messagebox.showinfo("Обновление", f"График для сигнала '{signal.Name}' обновлен по данным из таблицы.")

    # --- Остальные методы ---

    def on_select(self, event=None):
        """Вызывается при выборе сигнала в списке."""
        # Завершаем редактирование ячейки, если оно было активно
        if self._editing_cell_entry:
            # Пытаемся сохранить значение перед сменой сигнала
            self._on_edit_save(tk.Event()) # Имитируем событие для сохранения
            if self._editing_cell_entry: # Если сохранение не удалось (ошибка) и виджет еще есть
                self._editing_cell_entry.destroy()
                self._editing_cell_entry = None

        i = self._get_selected_index()
        if i is None:
            self._clear_entries()
            self._clear_points_table()
            self.update_from_table_btn.config(state='disabled')
            return

        if 0 <= i < len(self.signals):
            s = self.signals[i]
            self._update_entries(s) # Обновляем поля параметров
            self._populate_points_table(s) # Заполняем таблицу точек
            # Сбросим флаг редактирования из таблицы при смене сигнала
            # Пользователь должен явно нажать кнопку "Обновить по таблице" для нового сигнала
            self.updated_from_table_index = None
            # Перерисуем график, чтобы снять выделение предыдущего и выделить новый
            self.draw()


    def _update_entries(self, signal: Signal):
         """Обновляет поля ввода параметров на основе данных сигнала."""
         # Если сигнал был изменен через таблицу, поля параметров могут не соответствовать
         # PWL точкам. Показываем параметры как есть.
         self.ent['V0'].delete(0, 'end'); self.ent['V0'].insert(0, f"{signal.V0:g}")
         self.ent['V1'].delete(0, 'end'); self.ent['V1'].insert(0, f"{signal.V1:g}")
         self.ent['TD'].delete(0, 'end'); self.ent['TD'].insert(0, fmt(signal.TD))
         self.ent['TR'].delete(0, 'end'); self.ent['TR'].insert(0, fmt(signal.TR))
         self.ent['TF'].delete(0, 'end'); self.ent['TF'].insert(0, fmt(signal.TF))

         if self.mode == "high-low":
             self.ent['TH'].delete(0, 'end'); self.ent['TH'].insert(0, fmt(signal.TH))
             self.ent['TL'].delete(0, 'end'); self.ent['TL'].insert(0, fmt(signal.TL))
         else: # Режим PW/Period
             pulse_width = signal.TR + signal.TH + signal.TF
             period = signal.tp # tp = TR + TH + TF + TL
             self.ent['TH'].delete(0, 'end'); self.ent['TH'].insert(0, fmt(pulse_width))
             # Проверим, что период не нулевой перед форматированием
             period_str = fmt(period) if period > 1e-15 else "0s"
             self.ent['TL'].delete(0, 'end'); self.ent['TL'].insert(0, period_str)

         self.ent['N'].delete(0, 'end'); self.ent['N'].insert(0, signal.N)
         self.ent['Name'].delete(0, 'end'); self.ent['Name'].insert(0, signal.Name)

    def _clear_entries(self):
        for key in self.ent:
            self.ent[key].delete(0, 'end')

    def draw(self):
        """Перерисовывает все графики сигналов."""
        self.fig.clf() # Очищаем фигуру полностью
        if not self.signals:
            # Отображаем сообщение, если нет сигналов
            ax = self.fig.add_subplot(111)
            ax.text(0.5, 0.5, "Нет сигналов для отображения.\nДобавьте или загрузите сигнал.",
                    ha='center', va='center', fontsize=12, color='gray')
            ax.set_xticks([])
            ax.set_yticks([])
            self.canvas.draw_idle()
            self.toolbar.update() # Обновляем панель инструментов
            return

        # --- Получение параметров отображения ---
        xmax_str = self.xmax_var.get().strip().lower()
        xmax_sec_global = None
        try:
            if xmax_str not in ('', 'auto'):
                xmax_sec_global = parse_time(xmax_str)
                if xmax_sec_global <= 0:
                    print("Warning: X-max должен быть > 0. Используется auto.")
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
                     print(f"Warning: Шаг тиков X '{xtick_step_str}' должен быть > 0. Используется auto.")
                     tick_step_sec = None
                     self.xtick_step_var.set('auto')
             except ValueError as e:
                 print(f"Warning: Неверный формат шага тиков X '{xtick_step_str}'. Используется auto. Ошибка: {e}")
                 tick_step_sec = None
                 self.xtick_step_var.set('auto')

        n_signals = len(self.signals)
        idx_sel = self._get_selected_index() # Индекс выбранного в Listbox сигнала

        # Определяем общий масштаб и единицы, если X-max задан глобально
        common_scale, common_unit = (1, 's')
        if xmax_sec_global is not None:
            common_scale, common_unit = autoscale(xmax_sec_global)
        else:
            # Если X-max не задан, найдем максимальное время среди всех сигналов
            # для определения общего масштаба, чтобы оси X были согласованы
            max_total_time = 0
            for s in self.signals:
                 # Учитываем и PWL точки, если они есть
                signal_time = s.pwl_points[0][-1] if s.pwl_points and s.pwl_points[0] else s.total_time
                max_total_time = max(max_total_time, signal_time)
            if max_total_time > 0:
                common_scale, common_unit = autoscale(max_total_time)
            else:
                common_scale, common_unit = (1e9, 'ns') # По умолчанию наносекунды, если все времена 0

        # --- Рисование каждого сигнала ---
        for i, s in enumerate(self.signals):
            ax = self.fig.add_subplot(n_signals, 1, i + 1)

            # Получаем точки сигнала
            # Используем xmax_sec_global, если он задан, иначе None
            times_sec, voltages = s.get_waveform_points(xmax=xmax_sec_global)

            # Определяем реальное максимальное время на графике для этого сигнала
            actual_xmax_sec = xmax_sec_global if xmax_sec_global is not None else (times_sec[-1] if times_sec else 0)

            # Используем общий масштаб и единицы для оси X
            current_scale = common_scale
            current_unit = common_unit

            # Масштабируем время
            times_scaled = [t * current_scale for t in times_sec]

            # Рисуем график
            if times_scaled:
                ax.plot(times_scaled, voltages, lw=1.5, color='C0')
            else:
                # Если точек нет (например, сигнал с нулевой длительностью)
                # Нарисуем горизонтальную линию на уровне V0
                ax.plot([0, 1e-9 * current_scale], [s.V0, s.V0], lw=1.5, color='C0') # Рисуем очень короткий отрезок
                if actual_xmax_sec == 0 : actual_xmax_sec = 1e-9 # Минимальное время для оси

            # Настройка внешнего вида subplot'а
            title_style = {'fontweight': 'bold', 'color': 'darkblue'} if i == idx_sel else {}
            ax.set_title(s.Name, fontsize=10, loc='left', **title_style)
            ax.set_ylabel('V', fontsize=9)

            # Настройка пределов по Y
            v_min_data = min(voltages) if voltages else s.V0
            v_max_data = max(voltages) if voltages else s.V1
            # Учитываем V0 и V1 для определения диапазона
            v_min_eff = min(s.V0, s.V1, v_min_data)
            v_max_eff = max(s.V0, s.V1, v_max_data)
            v_range = v_max_eff - v_min_eff
            if abs(v_range) < 1e-9: v_range = 1.0 # Избегаем нулевого диапазона
            ax.set_ylim(v_min_eff - v_range * 0.15, v_max_eff + v_range * 0.15)

            # Настройка пределов по X
            xmax_limit_scaled = actual_xmax_sec * current_scale
            # Добавим небольшой отступ справа, если xmax не был задан явно
            xmax_display = xmax_limit_scaled * 1.02 if xmax_sec_global is None and xmax_limit_scaled > 0 else xmax_limit_scaled
            if xmax_display <= 0: xmax_display = 1 # Минимальный предел, если время 0

            ax.set_xlim(0, xmax_display)

            # Настройка тиков оси X
            if tick_step_sec is not None: # Задан пользователем
                base_step_scaled = tick_step_sec * current_scale
                if base_step_scaled > 1e-12: # Проверяем, что шаг не слишком мал для масштаба
                    locator = ticker.MultipleLocator(base=base_step_scaled)
                else:
                    print(f"Warning: Шаг тиков X ({fmt(tick_step_sec)}) слишком мал для масштаба '{current_unit}'. Используется auto.")
                    locator = ticker.MaxNLocator(nbins='auto', prune='both', integer=False)
            else: # Автоматический подбор
                locator = ticker.MaxNLocator(nbins='auto', prune='both', integer=False)

            ax.xaxis.set_major_locator(locator)
            ax.xaxis.set_major_formatter(unit_formatter(current_unit)) # Используем общий unit

            # Сетка и метка оси X (только для нижнего графика)
            ax.grid(True, ls=':', lw=0.6, color='lightgrey')
            if i != n_signals - 1:
                ax.set_xticklabels([]) # Скрываем метки для верхних графиков
            else:
                ax.set_xlabel(f'Время ({current_unit})', fontsize=9)

        # --- Финальная настройка и отрисовка ---
        try:
             # Используем constrained_layout для лучшего распределения места
            self.fig.set_layout_engine('constrained')#, h_pad=0.04, w_pad=0.02)
        except Exception as e_layout:
            print(f"Constrained layout failed: {e_layout}. Falling back to tight_layout.")
            try:
                 # Запасной вариант - tight_layout
                 self.fig.tight_layout(h_pad=0.6)
            except Exception as e_tight:
                 print(f"Tight layout also failed: {e_tight}. Layout may be suboptimal.")

        self.canvas.draw_idle() # Запрос на перерисовку в основном цикле Tk
        self.toolbar.update() # Обновляем панель инструментов Matplotlib

    # Методы загрузки/экспорта (оставлены без изменений, но могут потребовать адаптации,
    # если нужно сохранять/загружать PWL представление)
    def _choose_export_format(self) -> tuple[str | None, bool | None]:
        """
        Создает диалоговое окно для выбора формата экспорта и источника данных.
        Возвращает кортеж: (выбранный_формат, использовать_данные_таблицы)
        или (None, None) при отмене.
        """
        dialog = tk.Toplevel(self.master)
        dialog.title("Параметры экспорта")
        dialog.transient(self.master)
        dialog.grab_set()
        dialog.resizable(False, False)
        dialog.geometry("+{}+{}".format(self.master.winfo_rootx()+50, self.master.winfo_rooty()+50)) # Центрируем относительно гл. окна

        formats = ["PULSE", "PWL", "CSV"]
        if XLSX_SUPPORT:
            formats.append("XLSX")

        # --- Выбор формата ---
        format_frame = ttk.Frame(dialog, padding=5)
        format_frame.pack(fill='x', padx=10, pady=(10, 5))
        ttk.Label(format_frame, text="Формат экспорта:").pack(side='left')
        listbox = tk.Listbox(format_frame, height=len(formats), exportselection=False,
                            font=('Segoe UI', 10))
        listbox.pack(side='right', fill='x', expand=True, padx=(5, 0))
        for fmt in formats:
            listbox.insert('end', fmt)
        listbox.selection_set(0) # Выбираем первый по умолчанию

        # --- Выбор источника данных ---
        source_frame = ttk.Frame(dialog, padding=5)
        source_frame.pack(fill='x', padx=10, pady=5)
        self.export_use_table_var = tk.BooleanVar(value=False) # По умолчанию - по параметрам
        source_check = ttk.Checkbutton(source_frame,
                                       text="По точкам из таблицы (иначе по параметрам)",
                                       variable=self.export_use_table_var)
        source_check.pack(anchor='w')

        # --- Кнопки OK/Отмена ---
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(padx=10, pady=(5, 10), fill='x')

        selected_format = None
        export_from_table = None

        def on_ok():
            nonlocal selected_format, export_from_table
            selection = listbox.curselection()
            if selection:
                selected_format = formats[selection[0]]
                export_from_table = self.export_use_table_var.get()
            dialog.destroy()

        def on_cancel():
            nonlocal selected_format, export_from_table
            selected_format = None
            export_from_table = None
            dialog.destroy()

        ok_btn = ttk.Button(btn_frame, text="OK", command=on_ok, width=10)
        ok_btn.pack(side='left', expand=True, padx=5)
        cancel_btn = ttk.Button(btn_frame, text="Отмена", command=on_cancel, width=10)
        cancel_btn.pack(side='left', expand=True, padx=5)

        # Биндинги для Enter/Escape
        dialog.bind('<Return>', lambda e: ok_btn.invoke()) # Имитируем нажатие OK
        dialog.bind('<Escape>', lambda e: cancel_btn.invoke()) # Имитируем нажатие Отмена

        listbox.focus_set() # Фокус на список форматов для удобства

        dialog.wait_window()
        return selected_format, export_from_table

    def export(self):
        """Экспортирует данные сигналов в выбранный файл."""
        if not self.signals:
            messagebox.showinfo('Экспорт', 'Нет сигналов для экспорта.')
            return

        format_choice, use_table_data = self._choose_export_format()
        if format_choice is None: # Пользователь отменил
            return

        # --- Особая логика для PULSE формата ---
        # PULSE формат всегда основан на параметрах, игнорируем выбор источника
        force_pulse_export = False
        if format_choice == "PULSE":
            if use_table_data:
                 print("Info: Экспорт в PULSE всегда использует параметры сигнала, выбор 'По точкам из таблицы' игнорируется для этого формата.")
            force_pulse_export = True # Принудительно используем параметры для PULSE
            use_table_data_effective = False # Для отладки или логов
        else:
            force_pulse_export = not use_table_data # Если НЕ из таблицы, то принудительно по параметрам
            use_table_data_effective = use_table_data

        # Получаем X-max для экспорта (если задан)
        xmax_str = self.xmax_var.get().strip().lower()
        xmax_sec = None
        if xmax_str not in ('', 'auto'):
            try:
                xmax_sec = parse_time(xmax_str)
                if xmax_sec <= 0: xmax_sec = None
            except ValueError: xmax_sec = None

        # Определяем расширение файла
        if format_choice == "CSV": def_ext, types = ".csv", [("CSV files", "*.csv"), ("All files", "*.*")]
        elif format_choice == "XLSX": def_ext, types = ".xlsx", [("Excel files", "*.xlsx"), ("All files", "*.*")]
        else: def_ext, types = ".txt", [("Text files", "*.txt"), ("All files", "*.*")]

        filepath = filedialog.asksaveasfilename(
            defaultextension=def_ext,
            filetypes=types,
            initialfile=f"signals_{'params' if force_pulse_export else 'table'}{def_ext}", # Предлагаем имя файла в зависимости от источника
            title=f"Сохранить как {format_choice} файл (источник: {'Параметры' if force_pulse_export else 'Таблица'})"
        )
        if not filepath: return

        try:
            if format_choice == "PWL":
                with open(filepath, 'w', encoding='utf-8') as f:
                    for s in self.signals:
                        # Получаем точки с учетом выбора источника
                        times, voltages = s.get_waveform_points(xmax_sec, force_pulse=force_pulse_export)
                        points_str = " ".join(f"{t:.12g} {v:g}" for t, v in zip(times, voltages))
                        f.write(f"{s.Name}:PWL({points_str})\n")
                messagebox.showinfo('Экспорт завершен', f'Сигналы сохранены в PWL файл:\n{filepath}\n(Источник: {"Параметры" if force_pulse_export else "Таблица"})')

            elif format_choice == "PULSE":
                # Здесь всегда используем параметры (force_pulse_export = True)
                with open(filepath, 'w', encoding='utf-8') as f:
                    for s in self.signals:
                         # Используем внутренние параметры TR, TH, TF, TL, TP
                         tp_val = s.TR + s.TH + s.TF + s.TL
                         f.write(f"{s.Name}:PULSE({s.V0:g} {s.V1:g} {s.TD:.12g} {s.TR:.12g} {s.TF:.12g} {s.TH:.12g} {tp_val:.12g} {s.N})\n")
                messagebox.showinfo('Экспорт завершен', f'Сигналы сохранены в PULSE файл (всегда по параметрам):\n{filepath}')

            elif format_choice in ["CSV", "XLSX"]:
                # 1. Собрать все уникальные временные точки всех сигналов
                all_times = set()
                signals_points_map = {}
                for s in self.signals:
                    # Получаем точки с учетом выбора источника
                    times, voltages = s.get_waveform_points(xmax_sec, force_pulse=force_pulse_export)
                    all_times.update(times)
                    signals_points_map[s.Name] = (times, voltages)

                sorted_times = sorted(list(all_times))

                # 2. Создать строки данных (логика без изменений)
                headers = ['Time (s)'] + [s.Name for s in self.signals]
                data_rows = [headers]
                for t in sorted_times:
                    row = [t]
                    for s in self.signals:
                        signal_times, signal_voltages = signals_points_map[s.Name]
                        voltage_at_t = s.V0
                        found = False
                        for i in range(len(signal_times)):
                            # Используем небольшой допуск при сравнении времени <= t
                            if signal_times[i] <= t + 1e-15:
                                voltage_at_t = signal_voltages[i]
                                found = True
                            else:
                                break
                        if not found and signal_times and t < signal_times[0]:
                             voltage_at_t = s.V0
                        row.append(voltage_at_t)
                    data_rows.append(row)

                # 3. Записать в файл (логика без изменений)
                if format_choice == "CSV":
                    with open(filepath, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f, delimiter=',')
                        writer.writerows(data_rows)
                    messagebox.showinfo('Экспорт завершен', f'Временные диаграммы сохранены в CSV файл:\n{filepath}\n(Источник: {"Параметры" if force_pulse_export else "Таблица"})')
                else: # XLSX
                    wb = Workbook()
                    ws = wb.active
                    ws.title = "Signals"
                    for r_idx, row_data in enumerate(data_rows, 1):
                        ws.append(row_data)
                        if r_idx == 1:
                            for col in range(1, len(headers) + 1):
                                ws.cell(row=1, column=col).font = Font(bold=True)
                    for col in ws.columns:
                        max_length = 0
                        column_letter = get_column_letter(col[0].column)
                        for cell in col:
                            try:
                                if len(str(cell.value)) > max_length:
                                    max_length = len(str(cell.value))
                            except: pass
                        adjusted_width = (max_length + 2) * 1.1
                        ws.column_dimensions[column_letter].width = adjusted_width
                    wb.save(filepath)
                    messagebox.showinfo('Экспорт завершен', f'Временные диаграммы сохранены в Excel файл:\n{filepath}\n(Источник: {"Параметры" if force_pulse_export else "Таблица"})')

        except Exception as e:
            import traceback
            messagebox.showerror("Ошибка экспорта", f"Не удалось сохранить файл:\n{e}\n\n{traceback.format_exc()}")


    def load(self):
        """Загружает сигналы из выбранного файла."""
        filepath = filedialog.askopenfilename(
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Загрузить сигналы из файла"
        )
        if not filepath: return

        try:
            with open(filepath, 'r', encoding='utf-8') as f: lines = f.readlines()
        except IOError as e:
            messagebox.showerror("Ошибка чтения", f"Не удалось открыть файл:\n{e}")
            return

        loaded_signals = [] # Собираем сюда, чтобы не портить self.signals при ошибке
        parse_errors = []

        for lineno, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith('#'): continue # Пропускаем пустые и комментарии

            try:
                if ':' not in line: raise ValueError("Отсутствует разделитель ':'")
                name_part, data_part = line.split(':', 1)
                name = name_part.strip()
                data_part = data_part.strip().upper() # Приводим к верхнему регистру для PULSE/PWL

                if data_part.startswith("PULSE(") and data_part.endswith(")"):
                    inner = data_part[len("PULSE("):-1].strip()
                    tokens = inner.split()
                    if len(tokens) != 8: raise ValueError(f"PULSE: Ожидалось 8 значений, получено {len(tokens)}")
                    # Парсим значения PULSE (V0 V1 TD TR TF TH TP N)
                    v0 = float(tokens[0])
                    v1 = float(tokens[1])
                    # Время парсим через parse_time, чтобы поддержать единицы
                    td = parse_time(tokens[2])
                    tr = parse_time(tokens[3])
                    tf = parse_time(tokens[4])
                    th = parse_time(tokens[5])
                    tp = parse_time(tokens[6]) # Это T_PERIOD или T_PULSE? В старом формате это TP = TR+TH+TF+TL
                    n = int(tokens[7])
                    if n < 0: raise ValueError("PULSE: Число импульсов (N) не может быть отрицательным")

                    # Рассчитываем TL из TP
                    # TP = TR + TH + TF + TL
                    tl = tp - (tr + th + tf)
                    # Проверка на корректность времен
                    if tr < 0 or tf < 0 or th < 0 or td < 0: raise ValueError("PULSE: Времена не могут быть отрицательными")
                    if tl < -1e-12: # Допускаем небольшую погрешность вычислений
                       # Если TL отрицательный, возможно, TH был задан как PW?
                       # Попробуем интерпретировать 6-е значение (TH) как PW (Pulse Width)
                       pw_candidate = th
                       if pw_candidate >= tr + tf:
                           th_recalculated = pw_candidate - tr - tf
                           tl_recalculated = tp - pw_candidate # period - pulse_width
                           if tl_recalculated >= -1e-12:
                               print(f"Warning line {lineno}: Negative TL calculated. Assuming 6th parameter was PW, not TH. Recalculated TH={fmt(th_recalculated)}, TL={fmt(tl_recalculated)}")
                               th = th_recalculated
                               tl = max(0, tl_recalculated) # Убедимся, что не отрицательное из-за погрешности
                           else:
                               raise ValueError(f"PULSE: Вычисленное значение TL ({fmt(tl)}) отрицательно, и интерпретация 6-го параметра как PW тоже не подходит.")
                       else:
                           raise ValueError(f"PULSE: Вычисленное значение TL ({fmt(tl)}) отрицательно.")
                    else:
                        tl = max(0, tl) # Убедимся, что не отрицательное из-за погрешности

                    sig = Signal(V0=v0, V1=v1, TD=td, TR=tr, TF=tf, TH=th, TL=tl, N=n, Name=name)
                    loaded_signals.append(sig)

                elif data_part.startswith("PWL(") and data_part.endswith(")"):
                    inner = data_part[len("PWL("):-1].strip()
                    tokens = inner.split()
                    if not tokens: raise ValueError("PWL: Нет точек данных")
                    if len(tokens) % 2 != 0: raise ValueError("PWL: Нечетное число значений (ожидаются пары время-напряжение)")

                    pwl_times = []
                    pwl_voltages = []
                    last_t = -1.0
                    for i in range(0, len(tokens), 2):
                        t_str, v_str = tokens[i], tokens[i+1]
                        try:
                             t_val = parse_time(t_str) # Время с единицами
                             v_val = float(v_str)     # Напряжение просто число
                        except ValueError as e_pair:
                             raise ValueError(f"PWL: Ошибка в паре '{t_str} {v_str}': {e_pair}")

                        if t_val < last_t: raise ValueError(f"PWL: Время должно монотонно возрастать (нарушение: {fmt(t_val)} < {fmt(last_t)})")
                        # Допускаем одинаковое время для вертикальных фронтов
                        if t_val == last_t and pwl_times:
                            pwl_voltages[-1] = v_val # Обновляем напряжение последней точки
                        else:
                            pwl_times.append(t_val)
                            pwl_voltages.append(v_val)
                        last_t = t_val

                    if len(pwl_times) < 2: raise ValueError("PWL: Необходимо минимум 2 точки (начальная и конечная)")

                    # Создаем "пустой" сигнал PULSE, т.к. не можем надежно восстановить параметры
                    # V0 и V1 возьмем из первых двух уровней напряжения
                    v0_pwl = pwl_voltages[0]
                    v1_pwl = pwl_voltages[1] if len(pwl_voltages) > 1 else v0_pwl # Если только одна точка V1=V0
                    # Найдем первый не совпадающий с v0_pwl уровень, если возможно
                    for v in pwl_voltages:
                        if abs(v - v0_pwl) > 1e-9:
                             v1_pwl = v
                             break
                    # Создаем базовый сигнал (параметры будут игнорироваться при отрисовке, т.к. есть pwl_points)
                    sig = Signal(V0=v0_pwl, V1=v1_pwl, TD=0, TR=1e-9, TF=1e-9, TH=1e-9, TL=1e-9, N=0, Name=name)
                    # Сразу устанавливаем PWL точки
                    sig.set_pwl_points(pwl_times, pwl_voltages)
                    loaded_signals.append(sig)

                else:
                    raise ValueError("Неизвестный формат: строка должна начинаться с 'PULSE(' или 'PWL('")

            except Exception as ex:
                parse_errors.append(f"Строка {lineno}: {line}\n  Ошибка: {ex}")

        # Если были ошибки, сообщаем о них
        if parse_errors:
            error_details = "\n\n".join(parse_errors)
            messagebox.showerror("Ошибки загрузки", f"Обнаружены ошибки при разборе файла:\n\n{error_details}")
            # Решаем, загружать ли то, что удалось разобрать
            if not loaded_signals or not messagebox.askyesno("Продолжить?", "Несмотря на ошибки, загрузить успешно разобранные сигналы?"):
                return # Не загружаем ничего

        # Если ошибок не было или пользователь согласился продолжить
        self.signals = loaded_signals
        self.lb.delete(0, 'end')
        self._clear_points_table()
        self.update_from_table_btn.config(state='disabled')
        self.updated_from_table_index = None

        for s in self.signals:
            self.lb.insert('end', s.Name)

        if self.signals:
            self.lb.selection_set(0) # Выбираем первый сигнал
            self.on_select() # Обновляем поля и таблицу для первого сигнала
        else:
            self._clear_entries()

        self.draw() # Рисуем загруженные сигналы
        messagebox.showinfo("Загрузка завершена", f"Загружено {len(self.signals)} сигнал(ов).")


# ───── Запуск приложения ─────
def main():
    try:
        root = tk.Tk()
        # Попробуем установить тему Windows для более нативного вида (если доступно)
        try:
            from tkinter import font
            default_font = font.nametofont("TkDefaultFont")
            default_font.configure(family="Segoe UI", size=10)
            root.option_add("*Font", default_font)
            ttk.Style().theme_use('vista') # или 'xpnative', 'winnative'
        except Exception:
             print("Windows theme not available, using default.") # Оставляем clam по умолчанию

        app = PulseApp(root)
        root.mainloop()
    except Exception as e:
        import traceback
        # Используем tk окно для ошибки, если Tkinter еще работает
        try:
             root = tk.Tk()
             root.withdraw() # Скрываем основное окно
             messagebox.showerror("Критическая ошибка", f"Произошла ошибка при запуске:\n{e}\n\n{traceback.format_exc()}")
        except:
            # Если Tkinter совсем не работает, выводим в консоль
            print("Критическая ошибка:")
            print(e)
            print(traceback.format_exc())

if __name__ == '__main__':
    main()
