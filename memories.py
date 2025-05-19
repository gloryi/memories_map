import sys
import sqlite3
import re
from datetime import datetime
from dateutil.relativedelta import relativedelta, MO
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QLineEdit,
    QCheckBox,
    QMessageBox,
    QInputDialog,
    QSizePolicy,
)
from PyQt5.QtCore import Qt

W, H = 1920, 1080-200

conn = sqlite3.connect("memory_map.db")
cursor = conn.cursor()

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS user (
        id INTEGER PRIMARY KEY,
        birthdate TEXT NOT NULL
    )
"""
)

RAW_QUERY_ID = 0
RAW_QUERY_ORIGIN = 1
RAW_QUERY_TEXT = 2
RAW_QUERY_SHOW_ABOVE = 3
RAW_QUERY_SHOW_BELOW = 4
RAW_QUERY_SELECTED_LIST = 5

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS record (
        id INTEGER PRIMARY KEY,
        origin TEXT NOT NULL,
        text TEXT NOT NULL,
        show_above BOOLEAN NOT NULL DEFAULT 0,
        show_below BOOLEAN NOT NULL DEFAULT 0,
        selected_list TEXT,
        UNIQUE(origin, text)
    )
"""
)
conn.commit()


class TimeNode:
    LEVELS = [
        ("decade", 9, "years", 10),  # 0: A-I (0-8) representing 10-year spans
        ("year", 10, "years", 1),  # 1: A-J (0-9) years in decade
        ("quarter", 4, "months", 3),  # 2: A-D (0-3) quarters
        ("month", 3, "months", 1),  # 3: A-C (0-2) months in quarter
        ("week", 4, "days", 7),  # 4: A-D (0-3) ~week spans
        ("day", 8, "days", 1),  # 5: A-H (0-7) days in week span
        ("day_part", 3, "hours", 8),  # 6: A-C (0-2) 8-hour parts
        ("hour", 8, "hours", 1),  # 7: A-H (0-7) hours in part
    ]

    def __init__(self, key=""):
        self.key = key
        self.level = len(key)

    @property
    def max_children(self):
        return self.LEVELS[self.level][1] if self.level < 8 else 0

    def get_child_letters(self):
        if self.level >= 8:
            return []
        base = ord("A")
        return [chr(base + i) for i in range(self.max_children)]


class MemoryApp(QMainWindow):
    def __init__(self):
        super().__init__()
        print("super().__init__() OK")
        self.current_parent = TimeNode()
        self.selected_child = None
        self.user_birthdate = self.get_user_birthdate()
        self.user_birth_year = datetime(year = self.user_birthdate.year, month=1,day=1)
        self.init_ui()
        self.unpushed_commits = {}
        print("init_ui OK")
        self.refresh_view()
        print("refresh_view OK")

    def init_ui(self):
        self.setWindowTitle("Memory Map")
        self.setGeometry(100, 100, W, H)

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QHBoxLayout(main_widget)

        # Left panel
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        self.parent_label = QLabel("Lifetime")

        left_layout.addWidget(self.parent_label)

        self.child_grid = QVBoxLayout()
        self.child_grid_widgets = []
        left_layout.addLayout(self.child_grid)

        left_layout.addStretch(1)

        # Navigation buttons
        btn_layout = QHBoxLayout()
        self.btn_up = QPushButton("Go Up")
        self.btn_up.clicked.connect(self.go_up)
        btn_layout.addWidget(self.btn_up)

        self.btn_down = QPushButton("Go Down")
        self.btn_down.clicked.connect(self.go_down)
        btn_layout.addWidget(self.btn_down)

        left_layout.addLayout(btn_layout)

        left_layout.setStretch(1, 8)
        left_layout.setStretch(2, 2)


        # Right panel
        right_content = QWidget()
        self.right_layout = QVBoxLayout(right_content)

        # Record creation
        self.record_input = QLineEdit()
        # self.record_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        create_btn = QPushButton("Create Record")
        create_btn.clicked.connect(self.create_record)
        self.right_layout.addWidget(self.record_input)
        self.right_layout.addWidget(create_btn)

        # Record lists
        self.list_widgets = {}
        for list_name in ["Selected", "Self", "High TF", "Low TF"]:
            lbl = QLabel(list_name)
            self.right_layout.addWidget(lbl)
            scroll = QScrollArea()
            content = QWidget()
            right_scrollables_layout = QVBoxLayout(content)
            scroll.setWidget(content)
            scroll.setWidgetResizable(True)
            self.list_widgets[list_name] = (scroll, right_scrollables_layout)
            self.right_layout.addWidget(scroll)



        layout.addWidget(left_panel, 1)
        layout.addWidget(right_content, 1)

    def get_title(self, record_text):
        match = re.search(r'\[(.*?)\]', record_text)

        if match:
            return match.group(1)
        return record_text[:12]+"..."
    
    def get_body(self, record_text):
        match = re.search(r'\[(.*?)\]', record_text)

        title = ""
        if match:
            title = match.group(1)
        
        if title:
            return record_text.replace("["+title+"]", "")
        else:
            return record_text

    def prepare_childs_layout(self, not_nested_parent, nested_parent = None):

        parent = not_nested_parent if not_nested_parent else nested_parent

        layout_prepared = QVBoxLayout()

        letters = parent.get_child_letters()

        grid_structure = []
        if len(letters) == 9:
            grid_structure = [3, 3, 3]
        elif len(letters) == 10:
            grid_structure = [2, 3, 3, 2]
        elif len(letters) == 4:
            grid_structure = [2, 2]
        elif len(letters) == 3:
            grid_structure = [1, 2]
        elif len(letters) == 8:
            grid_structure = [3, 2, 3]
        else:
            grid_structure = [12]

        button_idx = 0
        for row in grid_structure:
            current_child_layout = QHBoxLayout()
            for col in range(row):

                if button_idx >= len(letters):
                    break

                letter = letters[button_idx]

                selected_records = self.fetch_selected_for_record(
                    parent.key + letter
                )

                btn_text = ""
                selected_record_text = ""
                if selected_records:
                    selected_record_text = self.get_title(selected_records[0][RAW_QUERY_TEXT])
                
                btn_text = self.get_timeframe_label(None, parent.key + letter)+ "\n" + selected_record_text
                
                if nested_parent:
                    btn = QPushButton(btn_text)
                else:
                    btn = QPushButton()
                
                child_time_node = TimeNode(parent.key + letter)
                if not nested_parent:
                    btn.setMinimumHeight(H//len(grid_structure))
                    btn.setCheckable(True)
                    btn.clicked.connect(lambda _, l=letter: self.select_child(l))
                    parent_layout = QVBoxLayout()
                    parent_layout.addWidget(QLabel(btn_text))
                    nested_layout = self.prepare_childs_layout(None, child_time_node)
                    parent_layout.addLayout(nested_layout)
                    btn.setLayout(parent_layout)
                
                if nested_parent:
                    btn.setEnabled(False)
                    
                childs_validity = list(self.is_valid_child(child_time_node.key+_) for _ in child_time_node.get_child_letters())
                any_valid_childs = True in childs_validity
                # TODO - process leafes
                if not any_valid_childs:
                    btn.setEnabled(False)

                if not nested_parent:
                    self.child_grid_widgets.append(btn)

                current_child_layout.addWidget(btn)
                button_idx += 1

            
            layout_prepared.addLayout(current_child_layout)
        
        return layout_prepared
        



    def refresh_view(self):
        for child_widget in self.child_grid_widgets:
            if child_widget:
                child_widget.deleteLater()
        self.child_grid_widgets = []

        # Update parent label
        self.parent_label.setText(self.get_timeframe_label(self.current_parent))


        self.child_grid.addLayout(self.prepare_childs_layout(self.current_parent))



        # Update navigation buttons
        self.btn_up.setEnabled(self.current_parent.level > 0)
        self.btn_down.setEnabled(
            bool(self.selected_child and self.current_parent.level < 7)
        )

        # Update right panel
        self.update_record_lists()

        print("refresh_view() refreshed")

    def select_child(self, letter):
        print(f"Select child triggered {self.current_parent.key} {letter}")
        self.selected_child = self.current_parent.key + letter
        self.refresh_view()

    def select_record(self, record, node_key):
        current_selection_string = record["selected_list"]
        entities = set(current_selection_string.split(","))

        if node_key in entities:
            entities.remove(node_key)
        else:
            entities.add(node_key)

        # entities.add(node_key)
        updated_selection_string = "," + ",".join([_ for _ in entities]) + ","
        updated_selection_string = updated_selection_string.replace(",,", ",")

        cursor.execute(
            """
            UPDATE record 
            SET selected_list = ?
            WHERE id = ?
            """,
            (updated_selection_string, record["id"]),
        )

        # Commit and close
        conn.commit()

        self.refresh_view()

    def delete_record(self, record, node_key):
        rec_id = record["id"]
        print(f" DELETE record id is {rec_id}")

        record_id = str(record["id"])

        cursor.execute('DELETE FROM record WHERE id = ?',[record_id])

        # Commit and close
        conn.commit()

        self.refresh_view()

    def set_check_above(self, state, record, node_key):
        is_checked = False if state == 0 else 1
        cursor.execute(
            """
            UPDATE record 
            SET show_above = ?
            WHERE id = ?
            """,
            (is_checked, record["id"]),
        )

        conn.commit()

        self.refresh_view()

    def set_check_below(self, state, record, node_key):
        print("set_check_below called")
        is_checked = False if state == 0 else 1
        cursor.execute(
            """
            UPDATE record 
            SET show_below = ?
            WHERE id = ?
            """,
            (is_checked, record["id"]),
        )

        conn.commit()

        self.refresh_view()

    def fetch_selected_for_record(self, identification_string):
        cursor.execute(
            """
            SELECT * FROM record
            WHERE ',' || selected_list || ',' LIKE '%,' || ? || ',%'
        """,
            (identification_string,),
        )

        results = cursor.fetchall()
        if results:
            print(results)
        return results
    
    def push_record_edit(self, record, node, edit_btn):

        updated_text = self.unpushed_commits[record["id"]]
        del self.unpushed_commits[record["id"]]
        edit_btn.setEnabled(False)

        cursor.execute(
            """
            UPDATE record 
            SET text = ?
            WHERE id = ?
            """,
            (updated_text, record["id"]),
        )

        conn.commit()

        self.refresh_view()

    
    def record_edited(self, record, node, title_field, text_field, edit_btn):
        original_text = record["text"]
        print(f"original_text = {original_text}")
        updated_text = ""

        changed_title = title_field.text()
        print(f"changed_title = {changed_title}")
        changed_text = text_field.text()
        print(f"changed_text = {changed_text}")

        if changed_text.startswith(changed_title.replace("...", "")) or not changed_title:
            changed_title = ""
            updated_text = original_text
        
        else:
            updated_text = "["+changed_title+"]"+changed_text
        
        print(updated_text)
        print(original_text)
        
        if updated_text == original_text:
            if edit_btn.isEnabled():
                edit_btn.setEnabled(False)
            if record["id"] in self.unpushed_commits:
                del self.unpushed_commits[record["id"]]
            return

        edit_btn.setEnabled(True)
        
        self.unpushed_commits[record["id"]] = updated_text



    def update_record_lists(self):
        for name, (scroll, layout) in self.list_widgets.items():
            records = []
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            if not self.selected_child:
                continue

            is_select_possible = True

            if name == "Self":
                records = self.get_records(origin=self.selected_child)
            elif name == "Selected":
                records = self.get_records(selected_list=self.selected_child)
                is_select_possible = False
            elif name == "High TF":
                print("Fetching high TF: preparing Query")
                records = self.get_records(show_below_parent=self.current_parent.key)
                records = [_ for _ in records if _["origin"] != self.selected_child]
            elif name == "Low TF":
                records = self.get_records(show_above_child=self.selected_child)
                records = [_ for _ in records if _["origin"] != self.selected_child]
            else:
                records = []

            for record in records:
                widget = QWidget()
                record_layout = QHBoxLayout(widget)

                title = QLineEdit(self.get_title(record["text"]))
                text = QLineEdit(self.get_body(record["text"]))

                edit_btn = QPushButton("E")
                if record["id"] in self.unpushed_commits:
                    edit_btn.setEnabled(True)
                else:
                    edit_btn.setEnabled(False)

                edit_btn.clicked.connect(lambda btn_pyqt_inner_state, r=record, n=self.selected_child, _edit_btn=edit_btn: self.push_record_edit(
                        r, n, _edit_btn
                    )
                )
                
                title.textEdited.connect(
                    lambda new_text, r=record, n=self.selected_child, _title=title, _text=text, _edit_btn=edit_btn: self.record_edited(
                        r, n, _title, _text, _edit_btn
                    )
                )

                text.textEdited.connect(
                    lambda new_text, r=record, n=self.selected_child, _title=title, _text=text, _edit_btn=edit_btn: self.record_edited(
                        r, n, _title, _text, _edit_btn
                    )
                )
                


                check_above = QCheckBox("▲")
                check_above.setChecked(record["show_above"])
                check_above.stateChanged.connect(
                    lambda state, r=record, n=self.selected_child: self.set_check_above(
                        state, r, n
                    )
                )
                check_below = QCheckBox("▼")
                check_below.setChecked(record["show_below"])
                check_below.stateChanged.connect(
                    lambda state, r=record, n=self.selected_child: self.set_check_below(
                        state, r, n
                    )
                )
                select_btn = QPushButton("Select" if is_select_possible else "Detach")
                select_btn.clicked.connect(
                    lambda _, r=record, n=self.selected_child: self.select_record(r, n)
                )
                delete_btn = QPushButton("Delete")
                delete_btn.clicked.connect(
                    lambda _, r=record, n=self.selected_child: self.delete_record(r, n)
                )

                record_layout.addWidget(title)
                record_layout.addWidget(text)
                record_layout.addWidget(edit_btn)
                record_layout.addWidget(check_above)
                record_layout.addWidget(check_below)
                record_layout.addWidget(select_btn)
                record_layout.addWidget(delete_btn)

                layout.addWidget(widget)

    def create_record(self):
        text = self.record_input.text()
        if not text or not self.selected_child:
            return

        cursor.execute(
            """
            INSERT INTO record (origin, text) VALUES (?, ?)
        """,
            (self.selected_child, text),
        )
        conn.commit()
        self.record_input.clear()
        self.update_record_lists()

    def go_up(self):
        if self.current_parent.level > 0:
            self.current_parent = TimeNode(self.current_parent.key[:-1])
            self.selected_child = None
            self.refresh_view()

    def go_down(self):
        if self.selected_child and self.current_parent.level < 7:
            self.current_parent = TimeNode(self.selected_child)
            self.selected_child = None
            self.refresh_view()

    # Helper methods
    def get_user_birthdate(self):
        cursor.execute("SELECT birthdate FROM user LIMIT 1")
        result = cursor.fetchone()
        if not result:
            birthdate, ok = QInputDialog.getText(
                self, "Setup", "Enter birthdate (YYYY-MM-DD):"
            )
            if ok:
                cursor.execute("INSERT INTO user (birthdate) VALUES (?)", (birthdate,))
                conn.commit()
                return datetime.strptime(birthdate, "%Y-%m-%d")
        return datetime.strptime(result[0], "%Y-%m-%d") if result else None

    def get_timeframe_label(self, node, key=""):
        key = key if key else node.key
        if not key:
            return "Lifetime"

        try:
            start_date = self.user_birth_year
            end_date = self.user_birth_year
            for level, (name, count, unit, amount) in enumerate(TimeNode.LEVELS):
                if level >= len(key):
                    break

                char = key[level]
                idx = ord(char) - ord("A")

                # Calculate time span for this level
                if unit == "years":
                    start_date += relativedelta(**{unit: idx * amount})
                    end_date = start_date + relativedelta(**{unit: amount})
                elif unit == "months":
                    start_date += relativedelta(months=idx * amount)
                    end_date = start_date + relativedelta(months=amount)
                elif unit == "days":
                    start_date += relativedelta(days=idx * amount)
                    end_date = start_date + relativedelta(days=amount)
                elif unit == "hours":
                    start_date += relativedelta(hours=idx * amount)
                    end_date = start_date + relativedelta(hours=amount)

            # TODO lables are better - still could be cleaned up
            if key and len(key) == 1:
                return f"{start_date.strftime('%Y')} - {end_date.strftime('%Y')}"
            elif key and len(key) == 2:
                return f"{start_date.strftime('%Y')}"
                # return f"{start_date.strftime('%Y')} - {end_date.strftime('%Y')}"
            elif key and len(key) == 3:
                return f"{start_date.strftime('%Y')} : {start_date.strftime('%b')} - {end_date.strftime('%b')}"
            elif key and len(key) == 4:
                return f"{start_date.strftime('%Y')} : {start_date.strftime('%b')}"
            elif key and len(key) == 5:
                return f"{start_date.strftime('%Y')} {start_date.strftime('%b')} : {start_date.strftime('%d')} - {end_date.strftime('%d')}"
            elif key and len(key) == 6:
                return f"{start_date.strftime('%Y')} {start_date.strftime('%b')} {start_date.strftime('%d')}"
            elif key and len(key) == 7:
                return f"{start_date.strftime('%Y')} {start_date.strftime('%b')} {start_date.strftime('%d')} : {start_date.strftime('%H')} - {end_date.strftime('%H')}"
            elif key and len(key) == 8:
                return f"{start_date.strftime('%Y')} {start_date.strftime('%b')} {start_date.strftime('%d')} : {start_date.strftime('%H')}"
            else:
                return f"{start_date.strftime('%Y-%m-%d %H')} - {end_date.strftime('%Y-%m-%d %H')}"
        except Exception as e:
            return f"Timeframe Error: {str(e)}"

    def is_valid_child(self, test_key):
        try:
            if not self.user_birthdate:
                print("No birthdate error?")
                return False
            
            now = datetime.now()

            current_date = self.user_birth_year
            for level, (_, count, unit, amount) in enumerate(TimeNode.LEVELS):
                if level >= len(test_key):
                    break

                idx = ord(test_key[level]) - ord("A")
                if unit == "years":
                    current_date += relativedelta(years=idx * amount)
                elif unit == "months":
                    current_date += relativedelta(months=idx * amount)
                elif unit == "days":
                    current_date += relativedelta(days=idx * amount)
                elif unit == "hours":
                    current_date += relativedelta(hours=idx * amount)

            return current_date <= now and current_date >= self.user_birthdate
        except Exception as e:
            print(f"is_valid_child exception {e}")
            return False

    def get_records(
        self,
        origin=None,
        selected_list=None,
        show_below_parent=None,
        show_above_child=None,
    ):
        try:
            queries = []
            params = []

            if origin:
                queries.append("origin = ?")
                params.append(origin)

            if selected_list:
                queries.append(
                    f"',' || selected_list || ',' LIKE '%,{selected_list},%'"
                )

            if show_below_parent:
                print(f"Fetching high TF: show_below_parent = {show_below_parent}")
                while show_below_parent:
                    queries.append(
                        "(origin = ? AND show_below = 1)"
                    )
                    params.append(show_below_parent)
                    show_below_parent = show_below_parent[
                        :-1
                    ]  # ABCDF - query -> ABCD - query -> ABC - query -> AB - query -> A - query -> end of loop

            if show_above_child:
                # ABCDF -> ABCDFE,True query, ABC,True not query, ABCDFA,False not query, ABCDAA,True not query
                queries.append("(origin LIKE ? || '%' AND show_above = 1)")
                params.append(show_above_child)

            if not queries:
                return []

            where_clause = " AND ".join(queries) if queries else "1=1"

            cursor.execute(
                f"""
                SELECT * 
                FROM record 
                WHERE {where_clause}
            """,
                params,
            )

            result = [
                {
                    "id": row[RAW_QUERY_ID],
                    "origin": row[RAW_QUERY_ORIGIN],
                    "text": row[RAW_QUERY_TEXT],
                    "show_above": bool(row[RAW_QUERY_SHOW_ABOVE]),
                    "show_below": bool(row[RAW_QUERY_SHOW_BELOW]),
                    "selected_list": row[RAW_QUERY_SELECTED_LIST] or "",
                }
                for row in cursor.fetchall()
            ]

            for rec in result:
                if rec["id"] in self.unpushed_commits:
                    rec["text"] = self.unpushed_commits[rec["id"]]

            return result 
        except Exception as e:
            QMessageBox.critical(self, "Database Error", str(e))
            return []

    def get_user_birthdate(self):
        cursor.execute("SELECT birthdate FROM user LIMIT 1")
        result = cursor.fetchone()
        if not result:
            birthdate, ok = QInputDialog.getText(
                self, "Setup", "Enter birthdate (YYYY-MM-DD):"
            )
            if ok and birthdate:
                try:
                    dt = datetime.strptime(birthdate, "%Y-%m-%d")
                    cursor.execute(
                        "INSERT INTO user (birthdate) VALUES (?)", (birthdate,)
                    )
                    conn.commit()
                    self.refresh_view()
                    return dt
                except Exception as e:
                    QMessageBox.critical(
                        self, "Error", f"Invalid date format: {str(e)}"
                    )
                    return self.get_user_birthdate()
        elif result:
            return datetime.strptime(result[0], "%Y-%m-%d")
        return None


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = MemoryApp()
    ex.show()
    sys.exit(app.exec_())
