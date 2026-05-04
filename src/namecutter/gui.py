from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .engine import apply_preview, build_preview
from .models import PreviewItem, ScanOptions


class NameCutterApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("NameCutter")
        self.root.geometry("1200x700")
        self.root.minsize(960, 560)

        self.source_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.limit_var = tk.StringVar(value="66")
        self.in_place_var = tk.BooleanVar(value=False)
        self.summary_var = tk.StringVar(value="Ready.")
        self.preview_items: list[PreviewItem] = []

        self._build_layout()
        self._toggle_in_place()

    def run(self) -> int:
        self.root.mainloop()
        return 0

    def _build_layout(self) -> None:
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        controls = ttk.Frame(root, padding=16)
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)

        ttk.Label(controls, text="Source Folder").grid(row=0, column=0, sticky="w", pady=4)
        source_entry = ttk.Entry(controls, textvariable=self.source_var)
        source_entry.grid(row=0, column=1, sticky="ew", padx=8, pady=4)
        ttk.Button(controls, text="Browse...", command=self._select_source).grid(
            row=0, column=2, sticky="ew", pady=4
        )

        ttk.Label(controls, text="Output Folder").grid(row=1, column=0, sticky="w", pady=4)
        self.output_entry = ttk.Entry(controls, textvariable=self.output_var)
        self.output_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=4)
        self.output_button = ttk.Button(controls, text="Browse...", command=self._select_output)
        self.output_button.grid(row=1, column=2, sticky="ew", pady=4)

        self.in_place_check = ttk.Checkbutton(
            controls,
            text="Output is the same as source (rename in place)",
            variable=self.in_place_var,
            command=self._toggle_in_place,
        )
        self.in_place_check.grid(row=2, column=1, sticky="w", pady=4)

        ttk.Label(controls, text="Max Path Length").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(controls, textvariable=self.limit_var, width=12).grid(
            row=3, column=1, sticky="w", padx=8, pady=4
        )

        buttons = ttk.Frame(controls)
        buttons.grid(row=4, column=1, sticky="w", pady=(12, 4))
        ttk.Button(buttons, text="Scan Preview", command=self._scan_preview).grid(
            row=0, column=0, padx=(0, 8)
        )
        ttk.Button(buttons, text="Run", command=self._run_preview).grid(row=0, column=1)

        table_frame = ttk.Frame(root, padding=(16, 0, 16, 8))
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = ("source", "target", "original_length", "action", "status", "reason")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        headings = {
            "source": "Source Path",
            "target": "Target Path",
            "original_length": "Original Path Length",
            "action": "Action",
            "status": "Status",
            "reason": "Reason",
        }
        widths = {
            "source": 300,
            "target": 300,
            "original_length": 140,
            "action": 100,
            "status": 90,
            "reason": 240,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor="w")

        vertical_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        horizontal_scroll = ttk.Scrollbar(
            table_frame, orient="horizontal", command=self.tree.xview
        )
        self.tree.configure(
            yscrollcommand=vertical_scroll.set,
            xscrollcommand=horizontal_scroll.set,
        )

        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical_scroll.grid(row=0, column=1, sticky="ns")
        horizontal_scroll.grid(row=1, column=0, sticky="ew")

        status_bar = ttk.Label(root, textvariable=self.summary_var, padding=(16, 8))
        status_bar.grid(row=2, column=0, sticky="ew")

    def _select_source(self) -> None:
        selected = filedialog.askdirectory(title="Choose the source folder")
        if not selected:
            return
        self.source_var.set(selected)
        if self.in_place_var.get():
            self.output_var.set(selected)

    def _select_output(self) -> None:
        selected = filedialog.askdirectory(title="Choose the output folder")
        if not selected:
            return
        self.output_var.set(selected)

    def _toggle_in_place(self) -> None:
        if self.in_place_var.get():
            self.output_var.set(self.source_var.get())
            self.output_entry.state(["disabled"])
            self.output_button.state(["disabled"])
        else:
            self.output_entry.state(["!disabled"])
            self.output_button.state(["!disabled"])

    def _scan_preview(self) -> None:
        try:
            options = self._read_options()
            self.preview_items = build_preview(options)
        except (FileNotFoundError, NotADirectoryError, ValueError) as error:
            messagebox.showerror("NameCutter", str(error))
            return

        self._refresh_tree()
        ready = sum(1 for item in self.preview_items if item.status == "ready")
        skipped = sum(1 for item in self.preview_items if item.status == "skip")
        self.summary_var.set(
            f"Preview ready. {len(self.preview_items)} file(s), {ready} ready, {skipped} skipped."
        )

    def _run_preview(self) -> None:
        if not self.preview_items:
            messagebox.showwarning("NameCutter", "Run Scan Preview before executing.")
            return
        if not messagebox.askyesno("NameCutter", "Apply the previewed changes now?"):
            return

        try:
            summary = apply_preview(self.preview_items)
        except OSError as error:
            messagebox.showerror("NameCutter", f"Execution failed: {error}")
            return

        self.summary_var.set(
            "Execution finished. "
            f"Processed {summary.processed}, changed {summary.changed}, "
            f"skipped {summary.skipped}, failed {summary.failed}."
        )
        messagebox.showinfo(
            "NameCutter",
            "Finished.\n"
            f"Processed: {summary.processed}\n"
            f"Changed: {summary.changed}\n"
            f"Skipped: {summary.skipped}\n"
            f"Failed: {summary.failed}",
        )

    def _read_options(self) -> ScanOptions:
        source_text = self.source_var.get().strip()
        output_text = self.output_var.get().strip()
        if not source_text:
            raise ValueError("Please choose a source folder.")

        if self.in_place_var.get():
            output_text = source_text
            self.output_var.set(source_text)
        elif not output_text:
            raise ValueError("Please choose an output folder.")

        try:
            limit = int(self.limit_var.get())
        except ValueError as error:
            raise ValueError("Max path length must be an integer.") from error

        if limit <= 0:
            raise ValueError("Max path length must be greater than zero.")

        source_dir = Path(source_text).expanduser()
        output_dir = Path(output_text).expanduser()

        return ScanOptions(
            source_dir=source_dir,
            output_dir=output_dir,
            max_path_length=limit,
            in_place=self.in_place_var.get() or source_dir == output_dir,
        )

    def _refresh_tree(self) -> None:
        for item_id in self.tree.get_children():
            self.tree.delete(item_id)

        for item in self.preview_items:
            self.tree.insert(
                "",
                "end",
                values=(
                    str(item.source_path),
                    str(item.target_path),
                    item.original_path_length,
                    item.action,
                    item.status,
                    item.reason,
                ),
            )
