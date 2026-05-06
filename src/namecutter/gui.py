from __future__ import annotations

from pathlib import Path
from typing import Callable
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .engine import apply_options, apply_preview, iter_preview
from .models import LimitMode, PreviewItem, ScanOptions

FULL_PREVIEW_LIMIT = 10_000
SAMPLE_PREVIEW_LIMIT = 2_000
WORKER_BATCH_SIZE = 250
WORKER_POLL_MS = 100

MODE_TO_LABEL: dict[LimitMode, str] = {
    "path": "Full Path Length",
    "filename": "File Name Length",
}
LABEL_TO_MODE = {label: mode for mode, label in MODE_TO_LABEL.items()}


class NameCutterApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("NameCutter")
        self.root.geometry("1200x760")
        self.root.minsize(960, 620)

        self.source_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.path_limit_var = tk.StringVar(value="66")
        self.filename_limit_var = tk.StringVar(value="66")
        self.limit_mode_var = tk.StringVar(value=MODE_TO_LABEL["path"])
        self.in_place_var = tk.BooleanVar(value=False)
        self.summary_var = tk.StringVar(value="Ready.")

        self.preview_items: list[PreviewItem] = []
        self.preview_is_partial = False
        self.preview_limit_mode: LimitMode = "path"
        self.preview_signature: tuple[str, str, str, int, int, bool] | None = None
        self.preview_total_scanned = 0
        self.preview_ready_count = 0
        self.preview_skipped_count = 0

        self.worker_queue: queue.Queue[tuple[str, object]] | None = None
        self.worker_thread: threading.Thread | None = None
        self.worker_kind: str | None = None

        self._build_layout()
        self._toggle_in_place()
        self._sync_limit_mode_controls()
        self._bind_option_change_handlers()

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
        self.source_entry = ttk.Entry(controls, textvariable=self.source_var)
        self.source_entry.grid(row=0, column=1, sticky="ew", padx=8, pady=4)
        self.source_button = ttk.Button(controls, text="Browse...", command=self._select_source)
        self.source_button.grid(row=0, column=2, sticky="ew", pady=4)

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

        ttk.Label(controls, text="Limit Mode").grid(row=3, column=0, sticky="w", pady=4)
        self.limit_mode_combo = ttk.Combobox(
            controls,
            textvariable=self.limit_mode_var,
            values=tuple(MODE_TO_LABEL.values()),
            state="readonly",
        )
        self.limit_mode_combo.grid(row=3, column=1, sticky="w", padx=8, pady=4)
        self.limit_mode_combo.bind("<<ComboboxSelected>>", self._on_limit_mode_selected)

        ttk.Label(controls, text="Max Path Length").grid(row=4, column=0, sticky="w", pady=4)
        self.path_limit_entry = ttk.Entry(controls, textvariable=self.path_limit_var, width=12)
        self.path_limit_entry.grid(row=4, column=1, sticky="w", padx=8, pady=4)

        ttk.Label(controls, text="Max File Name Length (without extension)").grid(
            row=5,
            column=0,
            sticky="w",
            pady=4,
        )
        self.filename_limit_entry = ttk.Entry(
            controls,
            textvariable=self.filename_limit_var,
            width=12,
        )
        self.filename_limit_entry.grid(row=5, column=1, sticky="w", padx=8, pady=4)

        buttons = ttk.Frame(controls)
        buttons.grid(row=6, column=1, sticky="w", pady=(12, 4))
        self.scan_button = ttk.Button(buttons, text="Scan Preview", command=self._scan_preview)
        self.scan_button.grid(row=0, column=0, padx=(0, 8))
        self.run_button = ttk.Button(buttons, text="Run", command=self._run_preview)
        self.run_button.grid(row=0, column=1)

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
            "original_length": 180,
            "action": 100,
            "status": 90,
            "reason": 260,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor="w")

        vertical_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        horizontal_scroll = ttk.Scrollbar(
            table_frame,
            orient="horizontal",
            command=self.tree.xview,
        )
        self.tree.configure(
            yscrollcommand=vertical_scroll.set,
            xscrollcommand=horizontal_scroll.set,
        )

        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical_scroll.grid(row=0, column=1, sticky="ns")
        horizontal_scroll.grid(row=1, column=0, sticky="ew")

        self.progress = ttk.Progressbar(root, mode="indeterminate")
        self.progress.grid(row=2, column=0, sticky="ew", padx=16)

        status_bar = ttk.Label(root, textvariable=self.summary_var, padding=(16, 8))
        status_bar.grid(row=3, column=0, sticky="ew")

    def _bind_option_change_handlers(self) -> None:
        for variable in (
            self.source_var,
            self.output_var,
            self.path_limit_var,
            self.filename_limit_var,
            self.in_place_var,
        ):
            variable.trace_add("write", self._on_option_value_changed)

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
        self._sync_control_states()

    def _on_limit_mode_selected(self, _event: object | None = None) -> None:
        self._sync_limit_mode_controls()
        self._invalidate_preview("Options changed. Scan Preview to refresh.")

    def _on_option_value_changed(self, *_args: object) -> None:
        if self.worker_kind is not None:
            return
        if self.in_place_var.get() and self.output_var.get() != self.source_var.get():
            self.output_var.set(self.source_var.get())
        self._invalidate_preview("Options changed. Scan Preview to refresh.")

    def _scan_preview(self) -> None:
        try:
            options = self._read_options()
        except (FileNotFoundError, NotADirectoryError, ValueError) as error:
            messagebox.showerror("NameCutter", str(error))
            return

        self.preview_items = []
        self.preview_is_partial = False
        self.preview_limit_mode = options.limit_mode
        self.preview_signature = self._signature_for_options(options)
        self.preview_total_scanned = 0
        self.preview_ready_count = 0
        self.preview_skipped_count = 0
        self._refresh_tree()
        self.summary_var.set("Scanning preview...")
        self._start_worker("scan", self._scan_preview_worker, options)

    def _run_preview(self) -> None:
        if self.preview_signature is None:
            messagebox.showwarning("NameCutter", "Run Scan Preview before executing.")
            return

        try:
            options = self._read_options()
        except (FileNotFoundError, NotADirectoryError, ValueError) as error:
            messagebox.showerror("NameCutter", str(error))
            return

        if self.preview_signature != self._signature_for_options(options):
            messagebox.showwarning(
                "NameCutter",
                "Options have changed since the last preview. Run Scan Preview again first.",
            )
            return

        if self.preview_is_partial:
            confirmed = messagebox.askyesno(
                "NameCutter",
                "The preview is showing sample rows only.\n"
                "NameCutter will rescan all files before applying changes.\n"
                "Continue?",
            )
        else:
            confirmed = messagebox.askyesno("NameCutter", "Apply the previewed changes now?")

        if not confirmed:
            return

        if self.preview_is_partial:
            self.summary_var.set("Rescanning all files before execution...")
            self._start_worker("apply", self._apply_options_worker, options)
            return

        self.summary_var.set("Executing previewed changes...")
        self._start_worker("apply", self._apply_preview_worker, list(self.preview_items))

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

        limit_mode = self._selected_limit_mode()
        path_limit = self._read_limit_value(
            self.path_limit_var.get(),
            "Max path length",
            required=limit_mode == "path",
            fallback=66,
        )
        filename_limit = self._read_limit_value(
            self.filename_limit_var.get(),
            "Max file name length",
            required=limit_mode == "filename",
            fallback=66,
        )

        source_dir = Path(source_text).expanduser()
        output_dir = Path(output_text).expanduser()

        return ScanOptions(
            source_dir=source_dir,
            output_dir=output_dir,
            max_path_length=path_limit,
            max_filename_length=filename_limit,
            limit_mode=limit_mode,
            in_place=self.in_place_var.get() or source_dir == output_dir,
        )

    def _read_limit_value(
        self,
        raw_value: str,
        label: str,
        *,
        required: bool,
        fallback: int,
    ) -> int:
        text = raw_value.strip()
        if not text:
            if required:
                raise ValueError(f"{label} is required.")
            return fallback

        try:
            value = int(text)
        except ValueError as error:
            if required:
                raise ValueError(f"{label} must be an integer.") from error
            return fallback

        if value <= 0:
            if required:
                raise ValueError(f"{label} must be greater than zero.")
            return fallback
        return value

    def _selected_limit_mode(self) -> LimitMode:
        return LABEL_TO_MODE[self.limit_mode_var.get()]

    def _signature_for_options(self, options: ScanOptions) -> tuple[str, str, str, int, int, bool]:
        source_dir = str(options.source_dir.expanduser().resolve(strict=False))
        output_dir = str(options.output_dir.expanduser().resolve(strict=False))
        return (
            source_dir,
            output_dir,
            options.limit_mode,
            options.max_path_length,
            options.max_filename_length,
            options.in_place,
        )

    def _start_worker(
        self,
        worker_kind: str,
        target: Callable[[object, queue.Queue[tuple[str, object]]], None],
        payload: object,
    ) -> None:
        self.worker_kind = worker_kind
        self.worker_queue = queue.Queue()
        self.worker_thread = threading.Thread(
            target=target,
            args=(payload, self.worker_queue),
            daemon=True,
        )
        self._sync_control_states()
        self.progress.start(10)
        self.worker_thread.start()
        self.root.after(WORKER_POLL_MS, self._poll_worker_queue)

    def _scan_preview_worker(
        self,
        options: ScanOptions,
        message_queue: queue.Queue[tuple[str, object]],
    ) -> None:
        try:
            batch: list[PreviewItem] = []
            for item in iter_preview(options):
                batch.append(item)
                if len(batch) >= WORKER_BATCH_SIZE:
                    message_queue.put(("preview_batch", batch))
                    batch = []

            if batch:
                message_queue.put(("preview_batch", batch))
            message_queue.put(("preview_done", None))
        except (FileNotFoundError, NotADirectoryError, OSError, ValueError) as error:
            message_queue.put(("worker_error", ("Preview failed", str(error))))

    def _apply_preview_worker(
        self,
        preview_items: list[PreviewItem],
        message_queue: queue.Queue[tuple[str, object]],
    ) -> None:
        try:
            summary = apply_preview(preview_items)
            message_queue.put(("apply_done", summary))
        except OSError as error:
            message_queue.put(("worker_error", ("Execution failed", str(error))))

    def _apply_options_worker(
        self,
        options: ScanOptions,
        message_queue: queue.Queue[tuple[str, object]],
    ) -> None:
        def report_progress(phase: str, processed: int, changed: int, skipped: int) -> None:
            message_queue.put(
                (
                    "apply_progress",
                    {
                        "phase": phase,
                        "processed": processed,
                        "changed": changed,
                        "skipped": skipped,
                    },
                )
            )

        try:
            summary = apply_options(options, progress_callback=report_progress)
            message_queue.put(("apply_done", summary))
        except OSError as error:
            message_queue.put(("worker_error", ("Execution failed", str(error))))

    def _poll_worker_queue(self) -> None:
        if self.worker_queue is None:
            return

        while True:
            try:
                message_type, payload = self.worker_queue.get_nowait()
            except queue.Empty:
                break
            self._handle_worker_message(message_type, payload)

        if self.worker_thread is None:
            return

        if self.worker_thread.is_alive() or (self.worker_queue is not None and not self.worker_queue.empty()):
            self.root.after(WORKER_POLL_MS, self._poll_worker_queue)
            return

        self._finish_worker()

    def _handle_worker_message(self, message_type: str, payload: object) -> None:
        if message_type == "preview_batch":
            self._consume_preview_batch(payload)
            return
        if message_type == "preview_done":
            self.summary_var.set(self._preview_summary_text(scanning=False))
            return
        if message_type == "apply_progress":
            self._update_apply_progress(payload)
            return
        if message_type == "apply_done":
            self._finish_worker()
            self._show_execution_summary(payload)
            return
        if message_type == "worker_error":
            failed_kind = self.worker_kind
            self._finish_worker()
            if failed_kind == "scan":
                self.preview_signature = None
            title, message = payload
            messagebox.showerror("NameCutter", f"{title}: {message}")

    def _consume_preview_batch(self, payload: object) -> None:
        batch = payload if isinstance(payload, list) else []
        partial_switched = False
        rows_to_append: list[PreviewItem] = []

        for item in batch:
            self.preview_total_scanned += 1
            if item.status == "skip":
                self.preview_skipped_count += 1
            else:
                self.preview_ready_count += 1

            if self.preview_is_partial:
                continue

            self.preview_items.append(item)
            if self.preview_total_scanned > FULL_PREVIEW_LIMIT:
                self.preview_is_partial = True
                self.preview_items = self.preview_items[:SAMPLE_PREVIEW_LIMIT]
                partial_switched = True
                rows_to_append.clear()
                continue

            rows_to_append.append(item)

        if partial_switched:
            self._refresh_tree()
        elif rows_to_append:
            self._append_tree_rows(rows_to_append)

        self.summary_var.set(self._preview_summary_text(scanning=True))

    def _update_apply_progress(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return

        phase = payload["phase"]
        processed = payload["processed"]
        changed = payload["changed"]
        skipped = payload["skipped"]

        if phase == "scan":
            self.summary_var.set(
                "Scanning all files before execution... "
                f"Processed {processed}, ready {processed - skipped}, skipped {skipped}."
            )
            return

        self.summary_var.set(
            "Applying changes... "
            f"Processed {processed}, changed {changed}, skipped {skipped}."
        )

    def _show_execution_summary(self, payload: object) -> None:
        summary = payload
        if not hasattr(summary, "processed"):
            return

        self.preview_signature = None
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

    def _finish_worker(self) -> None:
        self.progress.stop()
        self.worker_kind = None
        self.worker_thread = None
        self.worker_queue = None
        self._sync_control_states()

    def _sync_limit_mode_controls(self) -> None:
        path_active = self._selected_limit_mode() == "path"
        if path_active:
            self.path_limit_entry.state(["!disabled"])
            self.filename_limit_entry.state(["disabled"])
        else:
            self.path_limit_entry.state(["disabled"])
            self.filename_limit_entry.state(["!disabled"])

    def _sync_control_states(self) -> None:
        busy = self.worker_kind is not None

        for widget in (
            self.source_entry,
            self.source_button,
            self.in_place_check,
            self.scan_button,
            self.run_button,
        ):
            if busy:
                widget.state(["disabled"])
            else:
                widget.state(["!disabled"])

        if busy:
            self.output_entry.state(["disabled"])
            self.output_button.state(["disabled"])
            self.path_limit_entry.state(["disabled"])
            self.filename_limit_entry.state(["disabled"])
            self.limit_mode_combo.configure(state="disabled")
            return

        if self.in_place_var.get():
            self.output_entry.state(["disabled"])
            self.output_button.state(["disabled"])
        else:
            self.output_entry.state(["!disabled"])
            self.output_button.state(["!disabled"])

        self.limit_mode_combo.configure(state="readonly")
        self._sync_limit_mode_controls()

    def _invalidate_preview(self, message: str) -> None:
        if self.preview_signature is None:
            return
        self.preview_signature = None
        self.preview_items = []
        self.preview_is_partial = False
        self.preview_limit_mode = self._selected_limit_mode()
        self.preview_total_scanned = 0
        self.preview_ready_count = 0
        self.preview_skipped_count = 0
        self._refresh_tree()
        self.summary_var.set(message)

    def _preview_summary_text(self, *, scanning: bool) -> str:
        action = "Scanning preview..." if scanning else "Preview ready."
        summary = (
            f"{action} Scanned {self.preview_total_scanned} file(s), "
            f"{self.preview_ready_count} ready, {self.preview_skipped_count} skipped, "
            f"{len(self.preview_items)} shown."
        )
        if self.preview_is_partial:
            summary += " Showing sample rows only. Run will rescan all files."
        return summary

    def _refresh_tree(self) -> None:
        self._set_length_column(self.preview_limit_mode)
        for item_id in self.tree.get_children():
            self.tree.delete(item_id)

        if self.preview_items:
            self._append_tree_rows(self.preview_items)

    def _append_tree_rows(self, items: list[PreviewItem]) -> None:
        for item in items:
            self.tree.insert("", "end", values=self._tree_values(item))

    def _tree_values(self, item: PreviewItem) -> tuple[str, str, int, str, str, str]:
        original_length = (
            item.original_path_length
            if self.preview_limit_mode == "path"
            else item.original_name_length
        )
        return (
            str(item.source_path),
            str(item.target_path),
            original_length,
            item.action,
            item.status,
            item.reason,
        )

    def _set_length_column(self, limit_mode: LimitMode) -> None:
        heading = "Original Path Length" if limit_mode == "path" else "Original Name Length"
        self.tree.heading("original_length", text=heading)
