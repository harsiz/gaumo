"""
Gaumo Wallet - Bitcoin Core style GUI
Tabs: Overview, Send, Receive, Transactions, Peers, Mining, Console
"""
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import urllib.request
import urllib.error
from pathlib import Path

NODE_URL = 'http://localhost:8080'
REFRESH_INTERVAL = 3000  # ms


def api_get(path, timeout=5):
    with urllib.request.urlopen(f"{NODE_URL}{path}", timeout=timeout) as r:
        return json.loads(r.read())


def api_post(path, data, timeout=5):
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{NODE_URL}{path}", data=body,
        headers={'Content-Type': 'application/json'}, method='POST'
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


class GaumoWallet(tk.Tk):
    def __init__(self, wallet_path='wallet.json'):
        super().__init__()
        self.wallet_path = wallet_path
        self.wallet = None
        self._miner_proc = None
        self._miner_thread = None
        self._console_history = []
        self._console_history_idx = 0

        self.title("Gaumo Core")
        self.geometry("950x650")
        self.minsize(800, 550)

        self._build_menu()
        self._build_toolbar()
        self._build_notebook()
        self._build_statusbar()

        self._load_wallet()
        self._schedule_refresh()

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------

    def _build_menu(self):
        menubar = tk.Menu(self)

        # File
        m = tk.Menu(menubar, tearoff=0)
        m.add_command(label="Open Wallet...", command=self._open_wallet)
        m.add_command(label="New Wallet...", command=self._new_wallet)
        m.add_separator()
        m.add_command(label="Backup Wallet...", command=self._backup_wallet)
        m.add_separator()
        m.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=m)

        # Settings
        m = tk.Menu(menubar, tearoff=0)
        m.add_command(label="Change Node URL...", command=self._change_node_url)
        menubar.add_cascade(label="Settings", menu=m)

        # Help
        m = tk.Menu(menubar, tearoff=0)
        m.add_command(label="About Gaumo Core", command=self._about)
        menubar.add_cascade(label="Help", menu=m)

        self.config(menu=menubar)

    # ------------------------------------------------------------------
    # Toolbar
    # ------------------------------------------------------------------

    def _build_toolbar(self):
        tb = ttk.Frame(self, relief='raised')
        tb.pack(fill='x', side='top')
        ttk.Button(tb, text="Send", width=8, command=lambda: self._nb.select(1)).pack(side='left', padx=2, pady=2)
        ttk.Button(tb, text="Receive", width=8, command=lambda: self._nb.select(2)).pack(side='left', padx=2, pady=2)
        ttk.Button(tb, text="Refresh", width=8, command=self._refresh).pack(side='left', padx=2, pady=2)
        self._sync_var = tk.StringVar(value="Not connected")
        ttk.Label(tb, textvariable=self._sync_var, relief='sunken', width=40).pack(side='right', padx=4, pady=2)

    # ------------------------------------------------------------------
    # Notebook tabs
    # ------------------------------------------------------------------

    def _build_notebook(self):
        self._nb = ttk.Notebook(self)
        self._nb.pack(fill='both', expand=True)

        tabs = [
            ("Overview",     self._build_overview),
            ("Send",         self._build_send),
            ("Receive",      self._build_receive),
            ("Transactions", self._build_transactions),
            ("Peers",        self._build_peers),
            ("Mining",       self._build_mining),
            ("Console",      self._build_console),
        ]
        for label, builder in tabs:
            f = ttk.Frame(self._nb)
            self._nb.add(f, text=f"  {label}  ")
            builder(f)

    # ---- Overview ----

    def _build_overview(self, f):
        # Balance frame
        bf = ttk.LabelFrame(f, text="Balances")
        bf.pack(fill='x', padx=10, pady=8)

        ttk.Label(bf, text="Available:").grid(row=0, column=0, sticky='w', padx=8, pady=4)
        self._bal_avail = tk.StringVar(value="0.00000000 GAU")
        ttk.Label(bf, textvariable=self._bal_avail, font=('TkDefaultFont', 12, 'bold')).grid(row=0, column=1, sticky='w', padx=8)

        ttk.Label(bf, text="Address:").grid(row=1, column=0, sticky='w', padx=8, pady=4)
        self._overview_addr = tk.StringVar(value="—")
        ttk.Label(bf, textvariable=self._overview_addr, font=('Consolas', 9)).grid(row=1, column=1, sticky='w', padx=8)

        # Chain info
        cf = ttk.LabelFrame(f, text="Network")
        cf.pack(fill='x', padx=10, pady=4)
        self._net_info = tk.StringVar(value="—")
        ttk.Label(cf, textvariable=self._net_info).pack(anchor='w', padx=8, pady=4)

        # Recent transactions
        rtf = ttk.LabelFrame(f, text="Recent Transactions")
        rtf.pack(fill='both', expand=True, padx=10, pady=8)

        cols = ('Date', 'Type', 'Address', 'Amount')
        self._recent_tree = ttk.Treeview(rtf, columns=cols, show='headings', height=8)
        for c, w in zip(cols, (160, 80, 380, 140)):
            self._recent_tree.heading(c, text=c)
            self._recent_tree.column(c, width=w, anchor='w')
        sb = ttk.Scrollbar(rtf, orient='vertical', command=self._recent_tree.yview)
        self._recent_tree.configure(yscrollcommand=sb.set)
        self._recent_tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

    # ---- Send ----

    def _build_send(self, f):
        pad = {'padx': 12, 'pady': 5}

        ttk.Label(f, text="Pay To:").grid(row=0, column=0, sticky='w', **pad)
        self._send_to = tk.StringVar()
        ttk.Entry(f, textvariable=self._send_to, width=60, font=('Consolas', 9)).grid(row=0, column=1, columnspan=2, sticky='ew', **pad)

        ttk.Label(f, text="Label:").grid(row=1, column=0, sticky='w', **pad)
        self._send_label = tk.StringVar()
        ttk.Entry(f, textvariable=self._send_label, width=40).grid(row=1, column=1, sticky='ew', **pad)

        ttk.Label(f, text="Amount (GAU):").grid(row=2, column=0, sticky='w', **pad)
        self._send_amount = tk.StringVar()
        ttk.Entry(f, textvariable=self._send_amount, width=20).grid(row=2, column=1, sticky='w', **pad)

        ttk.Label(f, text="Fee (GAU):").grid(row=3, column=0, sticky='w', **pad)
        self._send_fee = tk.StringVar(value="0.001")
        ttk.Entry(f, textvariable=self._send_fee, width=20).grid(row=3, column=1, sticky='w', **pad)

        btn_frame = ttk.Frame(f)
        btn_frame.grid(row=4, column=0, columnspan=3, pady=10, padx=12, sticky='w')
        ttk.Button(btn_frame, text="Send Transaction", command=self._do_send).pack(side='left', padx=4)
        ttk.Button(btn_frame, text="Clear", command=self._clear_send).pack(side='left', padx=4)

        self._send_msg = tk.StringVar()
        ttk.Label(f, textvariable=self._send_msg, wraplength=500).grid(row=5, column=0, columnspan=3, padx=12, sticky='w')

        f.columnconfigure(1, weight=1)

    # ---- Receive ----

    def _build_receive(self, f):
        ttk.Label(f, text="Your Gaumo Address", font=('TkDefaultFont', 11, 'bold')).pack(pady=(20, 5))
        ttk.Label(f, text="Share this address to receive GAU payments.").pack()

        af = ttk.Frame(f)
        af.pack(pady=10, padx=40, fill='x')
        self._recv_addr = tk.StringVar(value="Loading...")
        e = ttk.Entry(af, textvariable=self._recv_addr, state='readonly',
                      font=('Consolas', 10), width=50)
        e.pack(side='left', fill='x', expand=True)
        ttk.Button(af, text="Copy", command=lambda: self._copy(self._recv_addr.get())).pack(side='left', padx=6)

        ttk.Separator(f, orient='horizontal').pack(fill='x', padx=40, pady=20)

        ttk.Label(f, text="Request Amount (optional):").pack()
        self._req_amount = tk.StringVar()
        ttk.Entry(f, textvariable=self._req_amount, width=20).pack(pady=5)
        ttk.Button(f, text="Generate Request URI", command=self._gen_uri).pack(pady=5)
        self._uri_var = tk.StringVar()
        ttk.Entry(f, textvariable=self._uri_var, state='readonly',
                  font=('Consolas', 9), width=60).pack(pady=5, padx=40, fill='x')

    # ---- Transactions ----

    def _build_transactions(self, f):
        toolbar = ttk.Frame(f)
        toolbar.pack(fill='x', padx=6, pady=4)
        ttk.Button(toolbar, text="Refresh", command=self._load_transactions).pack(side='left')
        ttk.Label(toolbar, text="Filter:").pack(side='left', padx=(10, 2))
        self._tx_filter = tk.StringVar()
        ttk.Entry(toolbar, textvariable=self._tx_filter, width=30).pack(side='left')
        ttk.Button(toolbar, text="Search", command=self._load_transactions).pack(side='left', padx=4)

        cols = ('Height', 'TxHash', 'Inputs', 'Outputs', 'Amount')
        self._tx_tree = ttk.Treeview(f, columns=cols, show='headings')
        for c, w in zip(cols, (70, 280, 60, 60, 140)):
            self._tx_tree.heading(c, text=c)
            self._tx_tree.column(c, width=w, anchor='w')
        vsb = ttk.Scrollbar(f, orient='vertical', command=self._tx_tree.yview)
        hsb = ttk.Scrollbar(f, orient='horizontal', command=self._tx_tree.xview)
        self._tx_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side='right', fill='y')
        hsb.pack(side='bottom', fill='x')
        self._tx_tree.pack(fill='both', expand=True, padx=6, pady=4)

    # ---- Peers ----

    def _build_peers(self, f):
        toolbar = ttk.Frame(f)
        toolbar.pack(fill='x', padx=6, pady=4)
        ttk.Button(toolbar, text="Refresh", command=self._load_peers).pack(side='left')
        ttk.Label(toolbar, text="Add peer:").pack(side='left', padx=(10, 2))
        self._add_peer_var = tk.StringVar()
        ttk.Entry(toolbar, textvariable=self._add_peer_var, width=25).pack(side='left')
        ttk.Button(toolbar, text="Connect", command=self._add_peer).pack(side='left', padx=4)

        cols = ('Host', 'Port', 'Height', 'Version')
        self._peer_tree = ttk.Treeview(f, columns=cols, show='headings')
        for c, w in zip(cols, (240, 80, 100, 80)):
            self._peer_tree.heading(c, text=c)
            self._peer_tree.column(c, width=w, anchor='w')
        vsb = ttk.Scrollbar(f, orient='vertical', command=self._peer_tree.yview)
        self._peer_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y')
        self._peer_tree.pack(fill='both', expand=True, padx=6, pady=4)

    # ---- Mining ----

    def _build_mining(self, f):
        # Controls
        ctrl = ttk.LabelFrame(f, text="Miner Controls")
        ctrl.pack(fill='x', padx=10, pady=8)

        ttk.Label(ctrl, text="Mining Address:").grid(row=0, column=0, sticky='w', padx=8, pady=4)
        self._mine_addr = tk.StringVar()
        ttk.Entry(ctrl, textvariable=self._mine_addr, width=50,
                  font=('Consolas', 9)).grid(row=0, column=1, sticky='ew', padx=8)

        ttk.Label(ctrl, text="Wallet File:").grid(row=1, column=0, sticky='w', padx=8, pady=4)
        self._mine_wallet = tk.StringVar(value='wallet.json')
        wf = ttk.Frame(ctrl)
        wf.grid(row=1, column=1, sticky='ew', padx=8)
        ttk.Entry(wf, textvariable=self._mine_wallet, width=40).pack(side='left')
        ttk.Button(wf, text="Browse", command=self._browse_wallet).pack(side='left', padx=4)

        ctrl.columnconfigure(1, weight=1)

        btn_frame = ttk.Frame(f)
        btn_frame.pack(fill='x', padx=10, pady=4)
        self._mine_btn = ttk.Button(btn_frame, text="Start Mining", command=self._toggle_mining)
        self._mine_btn.pack(side='left', padx=4)
        self._mine_status = tk.StringVar(value="Miner not running.")
        ttk.Label(btn_frame, textvariable=self._mine_status).pack(side='left', padx=10)

        # Stats
        sf = ttk.LabelFrame(f, text="Mining Stats")
        sf.pack(fill='x', padx=10, pady=4)
        self._mine_stats = tk.StringVar(value="—")
        ttk.Label(sf, textvariable=self._mine_stats, font=('Consolas', 9)).pack(anchor='w', padx=8, pady=4)

        # Log
        lf = ttk.LabelFrame(f, text="Miner Output")
        lf.pack(fill='both', expand=True, padx=10, pady=4)
        self._mine_log = scrolledtext.ScrolledText(lf, height=10, state='disabled',
                                                    font=('Consolas', 9), wrap='word')
        self._mine_log.pack(fill='both', expand=True, padx=4, pady=4)

    # ---- Console ----

    def _build_console(self, f):
        ttk.Label(f, text="Gaumo Console  —  type 'help' for available commands").pack(
            anchor='w', padx=6, pady=4)

        self._console_out = scrolledtext.ScrolledText(
            f, height=20, state='disabled', font=('Consolas', 9), wrap='word')
        self._console_out.pack(fill='both', expand=True, padx=6, pady=4)

        inp_frame = ttk.Frame(f)
        inp_frame.pack(fill='x', padx=6, pady=4)
        ttk.Label(inp_frame, text=">").pack(side='left')
        self._console_in = tk.StringVar()
        e = ttk.Entry(inp_frame, textvariable=self._console_in, font=('Consolas', 9))
        e.pack(side='left', fill='x', expand=True, padx=4)
        e.bind('<Return>', self._console_submit)
        e.bind('<Up>', self._console_history_up)
        e.bind('<Down>', self._console_history_down)
        ttk.Button(inp_frame, text="Run", command=self._console_submit).pack(side='left')

        self._console_print("Gaumo Core Console. Type 'help' to see commands.\n")

    # ------------------------------------------------------------------
    # Status bar
    # ------------------------------------------------------------------

    def _build_statusbar(self):
        sb = ttk.Frame(self, relief='sunken')
        sb.pack(fill='x', side='bottom')
        self._sb_height = tk.StringVar(value="Height: —")
        self._sb_peers = tk.StringVar(value="Peers: —")
        self._sb_mempool = tk.StringVar(value="Mempool: —")
        self._sb_conn = tk.StringVar(value="●  Not connected")
        ttk.Label(sb, textvariable=self._sb_conn, width=20).pack(side='left', padx=6)
        ttk.Separator(sb, orient='vertical').pack(side='left', fill='y', pady=2)
        ttk.Label(sb, textvariable=self._sb_height, width=14).pack(side='left', padx=6)
        ttk.Separator(sb, orient='vertical').pack(side='left', fill='y', pady=2)
        ttk.Label(sb, textvariable=self._sb_peers, width=12).pack(side='left', padx=6)
        ttk.Separator(sb, orient='vertical').pack(side='left', fill='y', pady=2)
        ttk.Label(sb, textvariable=self._sb_mempool, width=16).pack(side='left', padx=6)

    # ------------------------------------------------------------------
    # Wallet management
    # ------------------------------------------------------------------

    def _load_wallet(self):
        try:
            from gaumo.wallet import Wallet
            if Path(self.wallet_path).exists():
                self.wallet = Wallet.load(self.wallet_path)
            else:
                self.wallet = Wallet.generate()
                self.wallet.save(self.wallet_path)
                messagebox.showinfo("New Wallet",
                    f"A new wallet has been created.\n\nAddress:\n{self.wallet.address}\n\n"
                    f"Saved to: {self.wallet_path}\n\nBACK UP YOUR WALLET FILE!")
            addr = self.wallet.address
            self._recv_addr.set(addr)
            self._overview_addr.set(addr)
            self._mine_addr.set(addr)
            self._mine_wallet.set(self.wallet_path)
        except Exception as e:
            messagebox.showerror("Wallet Error", str(e))

    def _open_wallet(self):
        path = filedialog.askopenfilename(
            title="Open Wallet", filetypes=[("JSON wallet", "*.json"), ("All files", "*.*")])
        if path:
            self.wallet_path = path
            self._load_wallet()

    def _new_wallet(self):
        path = filedialog.asksaveasfilename(
            title="Save New Wallet As", defaultextension=".json",
            filetypes=[("JSON wallet", "*.json")])
        if not path:
            return
        if Path(path).exists():
            if not messagebox.askyesno("Overwrite?",
                    f"'{path}' already exists.\nOverwrite? This cannot be undone."):
                return
        from gaumo.wallet import Wallet
        w = Wallet.generate()
        w.save(path)
        messagebox.showinfo("Wallet Created",
            f"New wallet created!\n\nAddress:\n{w.address}\n\nSaved to:\n{path}")
        self.wallet_path = path
        self._load_wallet()

    def _backup_wallet(self):
        if not self.wallet:
            messagebox.showerror("Error", "No wallet loaded.")
            return
        path = filedialog.asksaveasfilename(
            title="Backup Wallet To", defaultextension=".json",
            filetypes=[("JSON wallet", "*.json")])
        if path:
            import shutil
            shutil.copy2(self.wallet_path, path)
            messagebox.showinfo("Backup", f"Wallet backed up to:\n{path}")

    # ------------------------------------------------------------------
    # Refresh / data loading
    # ------------------------------------------------------------------

    def _schedule_refresh(self):
        self._refresh()
        self.after(REFRESH_INTERVAL, self._schedule_refresh)

    def _refresh(self):
        threading.Thread(target=self._do_refresh, daemon=True).start()

    def _do_refresh(self):
        try:
            status = api_get('/status')
            h = status['height']
            p = status['peers']
            m = status['mempool_size']
            target = status.get('target', '?')[:16]

            self.after(0, lambda: self._sb_conn.set("●  Connected"))
            self.after(0, lambda: self._sb_height.set(f"Height: {h}"))
            self.after(0, lambda: self._sb_peers.set(f"Peers: {p}"))
            self.after(0, lambda: self._sb_mempool.set(f"Mempool: {m} tx"))
            self.after(0, lambda: self._sync_var.set(
                f"Height: {h}  |  Peers: {p}  |  Target: {target}..."))
            self.after(0, lambda: self._net_info.set(
                f"Height: {h}  |  Peers: {p}  |  Mempool: {m} tx  |  Target: {target}..."))

            if self.wallet:
                try:
                    bal = api_get(f'/balance/{self.wallet.address}')
                    b = f"{bal['balance_gau']:.8f} GAU"
                    self.after(0, lambda: self._bal_avail.set(b))
                except Exception:
                    pass

            self._load_peers()
            self._load_transactions()

        except Exception as e:
            msg = str(e)
            self.after(0, lambda: self._sb_conn.set("●  Offline"))
            self.after(0, lambda: self._sync_var.set(f"Not connected: {msg}"))

    def _load_peers(self):
        def run():
            try:
                peers = api_get('/peers')
                self.after(0, lambda: self._update_peers(peers))
            except Exception:
                pass
        threading.Thread(target=run, daemon=True).start()

    def _update_peers(self, peers):
        self._peer_tree.delete(*self._peer_tree.get_children())
        for p in peers:
            self._peer_tree.insert('', 'end', values=(
                p.get('host', '?'), p.get('port', '?'),
                p.get('height', '?'), p.get('version', '?')
            ))

    def _load_transactions(self):
        def run():
            try:
                blocks = api_get('/chain?start=0&limit=200')
                rows = []
                filt = self._tx_filter.get().strip().lower()
                for b in reversed(blocks):
                    for tx in b['transactions']:
                        h = tx.get('tx_hash', '')[:32] + '...'
                        ins = len(tx.get('inputs', []))
                        outs = len(tx.get('outputs', []))
                        amt = sum(o['amount'] for o in tx.get('outputs', [])) / 1e8
                        row = (b['index'], h, ins, outs, f"{amt:.8f} GAU")
                        if not filt or any(filt in str(v).lower() for v in row):
                            rows.append(row)
                self.after(0, lambda: self._update_tx_tree(rows))
            except Exception:
                pass
        threading.Thread(target=run, daemon=True).start()

    def _update_tx_tree(self, rows):
        self._tx_tree.delete(*self._tx_tree.get_children())
        for row in rows[:200]:
            self._tx_tree.insert('', 'end', values=row)

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    def _do_send(self):
        if not self.wallet:
            messagebox.showerror("Error", "No wallet loaded.")
            return
        recipient = self._send_to.get().strip()
        if not recipient:
            messagebox.showerror("Error", "Enter a recipient address.")
            return
        try:
            amount = float(self._send_amount.get())
            fee = float(self._send_fee.get())
        except ValueError:
            messagebox.showerror("Error", "Invalid amount or fee.")
            return
        if not messagebox.askyesno("Confirm Send",
                f"Send {amount:.8f} GAU to:\n{recipient}\n\nFee: {fee:.8f} GAU\n\nProceed?"):
            return
        threading.Thread(target=self._submit_tx, args=(recipient, amount, fee), daemon=True).start()

    def _submit_tx(self, recipient, amount_gau, fee_gau):
        try:
            from gaumo.core.utxo import UTXOSet, UTXO
            utxo_list = api_get(f'/utxos/{self.wallet.address}')
            utxo_set = UTXOSet()
            for u in utxo_list:
                utxo_set.add(UTXO.from_dict(u))
            amount_sat = int(amount_gau * 1e8)
            fee_sat = int(fee_gau * 1e8)
            tx = self.wallet.create_transaction(recipient, amount_sat, fee_sat, utxo_set)
            result = api_post('/transaction', tx.to_dict())
            msg = f"Transaction sent!\nTX ID: {result['tx_hash']}"
            self.after(0, lambda: self._send_msg.set(f"Sent: {result['tx_hash'][:24]}..."))
            self.after(0, lambda: messagebox.showinfo("Transaction Sent", msg))
        except Exception as e:
            err = str(e)
            self.after(0, lambda: self._send_msg.set(f"Error: {err}"))
            self.after(0, lambda: messagebox.showerror("Send Failed", err))

    def _clear_send(self):
        self._send_to.set('')
        self._send_label.set('')
        self._send_amount.set('')
        self._send_fee.set('0.001')
        self._send_msg.set('')

    # ------------------------------------------------------------------
    # Receive
    # ------------------------------------------------------------------

    def _gen_uri(self):
        addr = self._recv_addr.get()
        amt = self._req_amount.get().strip()
        uri = f"gaumo:{addr}"
        if amt:
            uri += f"?amount={amt}"
        self._uri_var.set(uri)
        self._copy(uri)

    # ------------------------------------------------------------------
    # Mining
    # ------------------------------------------------------------------

    def _browse_wallet(self):
        path = filedialog.askopenfilename(
            title="Select Wallet File", filetypes=[("JSON wallet", "*.json")])
        if path:
            self._mine_wallet.set(path)

    def _toggle_mining(self):
        if self._miner_proc and self._miner_proc.poll() is None:
            self._stop_mining()
        else:
            self._start_mining()

    def _start_mining(self):
        wallet_path = self._mine_wallet.get().strip() or 'wallet.json'
        self._mine_log_append("Starting miner...\n")
        try:
            cmd = [sys.executable, '-m', 'gaumo.cli.cli', 'mine',
                   '--wallet', wallet_path, '--api-port', '8080']
            self._miner_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=str(Path(self.wallet_path).parent),
            )
            self._mine_btn.config(text="Stop Mining")
            self._mine_status.set("Miner running...")
            self._miner_thread = threading.Thread(
                target=self._read_miner_output, daemon=True)
            self._miner_thread.start()
        except Exception as e:
            messagebox.showerror("Mining Error", str(e))

    def _stop_mining(self):
        if self._miner_proc:
            self._miner_proc.terminate()
            self._miner_proc = None
        self._mine_btn.config(text="Start Mining")
        self._mine_status.set("Miner stopped.")
        self._mine_log_append("Miner stopped.\n")

    def _read_miner_output(self):
        proc = self._miner_proc
        for line in proc.stdout:
            if proc.poll() is not None and not line:
                break
            self.after(0, lambda l=line: self._mine_log_append(l))
            # Parse stats from log lines
            if 'Rate:' in line and 'H/s' in line:
                self.after(0, lambda l=line: self._mine_stats.set(l.strip()))
        self.after(0, lambda: self._mine_status.set("Miner finished."))
        self.after(0, lambda: self._mine_btn.config(text="Start Mining"))

    def _mine_log_append(self, text):
        self._mine_log.configure(state='normal')
        self._mine_log.insert('end', text)
        self._mine_log.see('end')
        self._mine_log.configure(state='disabled')

    # ------------------------------------------------------------------
    # Console
    # ------------------------------------------------------------------

    def _console_submit(self, event=None):
        cmd = self._console_in.get().strip()
        if not cmd:
            return
        self._console_history.append(cmd)
        self._console_history_idx = len(self._console_history)
        self._console_in.set('')
        self._console_print(f"> {cmd}\n")
        threading.Thread(target=self._run_console_cmd, args=(cmd,), daemon=True).start()

    def _run_console_cmd(self, cmd):
        parts = cmd.strip().split()
        if not parts:
            return
        builtin = parts[0].lower()

        # Built-in help
        if builtin == 'help':
            help_text = (
                "Available commands:\n"
                "  status                    - Node status\n"
                "  balance <address>         - Check balance\n"
                "  peers                     - List peers\n"
                "  mempool                   - Show mempool\n"
                "  block <height|hash>       - Show block\n"
                "  wallet-info               - Show loaded wallet info\n"
                "  clear                     - Clear console\n"
                "  help                      - Show this help\n"
                "  <any gaumo CLI command>   - Runs via gaumo CLI\n"
            )
            self.after(0, lambda: self._console_print(help_text + '\n'))
            return

        if builtin == 'clear':
            self.after(0, self._console_clear)
            return

        if builtin == 'wallet-info':
            if self.wallet:
                info = (f"Address : {self.wallet.address}\n"
                        f"WIF     : {self.wallet.wif}\n"
                        f"PubKey  : {self.wallet.public_key.hex()}\n")
                self.after(0, lambda: self._console_print(info + '\n'))
            else:
                self.after(0, lambda: self._console_print("No wallet loaded.\n\n"))
            return

        # Try API shortcuts
        try:
            if builtin == 'status':
                data = api_get('/status')
                self.after(0, lambda: self._console_print(json.dumps(data, indent=2) + '\n\n'))
                return
            if builtin == 'peers':
                data = api_get('/peers')
                self.after(0, lambda: self._console_print(json.dumps(data, indent=2) + '\n\n'))
                return
            if builtin == 'mempool':
                data = api_get('/mempool')
                self.after(0, lambda: self._console_print(json.dumps(data, indent=2) + '\n\n'))
                return
            if builtin == 'balance' and len(parts) >= 2:
                data = api_get(f'/balance/{parts[1]}')
                self.after(0, lambda: self._console_print(json.dumps(data, indent=2) + '\n\n'))
                return
            if builtin == 'block' and len(parts) >= 2:
                data = api_get(f'/block/{parts[1]}')
                self.after(0, lambda: self._console_print(json.dumps(data, indent=2) + '\n\n'))
                return
        except Exception as e:
            err = str(e)
            self.after(0, lambda: self._console_print(f"Error: {err}\n\n"))
            return

        # Fall back to running as gaumo CLI subprocess
        try:
            result = subprocess.run(
                [sys.executable, '-m', 'gaumo.cli.cli'] + parts,
                capture_output=True, text=True, timeout=15
            )
            out = result.stdout + result.stderr
            self.after(0, lambda: self._console_print(out + '\n'))
        except Exception as e:
            err = str(e)
            self.after(0, lambda: self._console_print(f"Error: {err}\n\n"))

    def _console_print(self, text):
        self._console_out.configure(state='normal')
        self._console_out.insert('end', text)
        self._console_out.see('end')
        self._console_out.configure(state='disabled')

    def _console_clear(self):
        self._console_out.configure(state='normal')
        self._console_out.delete('1.0', 'end')
        self._console_out.configure(state='disabled')

    def _console_history_up(self, event):
        if self._console_history and self._console_history_idx > 0:
            self._console_history_idx -= 1
            self._console_in.set(self._console_history[self._console_history_idx])

    def _console_history_down(self, event):
        if self._console_history_idx < len(self._console_history) - 1:
            self._console_history_idx += 1
            self._console_in.set(self._console_history[self._console_history_idx])
        else:
            self._console_history_idx = len(self._console_history)
            self._console_in.set('')

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def _copy(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)

    def _add_peer(self):
        addr = self._add_peer_var.get().strip()
        self._console_print(f"[Peers] Manual peer add not yet supported via API: {addr}\n")

    def _change_node_url(self):
        global NODE_URL
        d = tk.Toplevel(self)
        d.title("Change Node URL")
        d.geometry("360x120")
        d.resizable(False, False)
        ttk.Label(d, text="Node URL:").pack(pady=(16, 4))
        v = tk.StringVar(value=NODE_URL)
        ttk.Entry(d, textvariable=v, width=40).pack()
        def _save():
            global NODE_URL
            NODE_URL = v.get().rstrip('/')
            d.destroy()
        ttk.Button(d, text="Save", command=_save).pack(pady=10)

    def _about(self):
        messagebox.showinfo("About Gaumo Core",
            "Gaumo Core\nVersion 0.1.0\n\n"
            "A modular Python cryptocurrency.\n"
            "UTXO model · SHA-256 PoW · Outbound P2P\n\n"
            "github.com/harsiz/gaumo")


def launch_gui(node_url='http://localhost:8080', wallet_path='wallet.json'):
    global NODE_URL
    NODE_URL = node_url
    app = GaumoWallet(wallet_path=wallet_path)
    app.mainloop()


if __name__ == '__main__':
    launch_gui()
