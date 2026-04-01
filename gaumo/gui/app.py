"""
Gaumo Wallet GUI built with Tkinter.
Features: balance display, send transactions, recent activity.
"""
import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import urllib.request
from pathlib import Path


class GaumoApp(tk.Tk):
    def __init__(self, node_url='http://localhost:8080', wallet_path='wallet.json'):
        super().__init__()
        self.node_url = node_url.rstrip('/')
        self.wallet_path = wallet_path
        self.wallet = None

        self.title("Gaumo Wallet")
        self.geometry("800x600")
        self.resizable(True, True)
        self.configure(bg='#1a1a2e')

        self._setup_styles()
        self._build_ui()
        self._load_wallet()
        self._start_refresh()

    def _setup_styles(self):
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('TFrame', background='#1a1a2e')
        style.configure('TLabel', background='#1a1a2e', foreground='#e0e0e0',
                        font=('Segoe UI', 10))
        style.configure('Title.TLabel', background='#1a1a2e', foreground='#00d4ff',
                        font=('Segoe UI', 14, 'bold'))
        style.configure('Balance.TLabel', background='#1a1a2e', foreground='#00ff88',
                        font=('Segoe UI', 24, 'bold'))
        style.configure('TButton', background='#16213e', foreground='#e0e0e0',
                        font=('Segoe UI', 10), relief='flat', borderwidth=1)
        style.map('TButton', background=[('active', '#0f3460')])
        style.configure('TEntry', fieldbackground='#16213e', foreground='#e0e0e0',
                        insertcolor='#e0e0e0')
        style.configure('TNotebook', background='#1a1a2e', tabposition='n')
        style.configure('TNotebook.Tab', background='#16213e', foreground='#e0e0e0',
                        padding=[10, 5])
        style.map('TNotebook.Tab', background=[('selected', '#0f3460')],
                  foreground=[('selected', '#00d4ff')])

    def _build_ui(self):
        # Header
        header = ttk.Frame(self)
        header.pack(fill='x', padx=20, pady=10)
        ttk.Label(header, text="GAUMO WALLET", style='Title.TLabel').pack(side='left')

        self._status_var = tk.StringVar(value="Connecting...")
        ttk.Label(header, textvariable=self._status_var, style='TLabel').pack(side='right')

        # Notebook (tabs)
        nb = ttk.Notebook(self)
        nb.pack(fill='both', expand=True, padx=20, pady=5)

        self._tab_wallet = ttk.Frame(nb)
        self._tab_send = ttk.Frame(nb)
        self._tab_explorer = ttk.Frame(nb)

        nb.add(self._tab_wallet, text='  Wallet  ')
        nb.add(self._tab_send, text='  Send  ')
        nb.add(self._tab_explorer, text='  Explorer  ')

        self._build_wallet_tab()
        self._build_send_tab()
        self._build_explorer_tab()

    def _build_wallet_tab(self):
        f = self._tab_wallet
        f.configure(style='TFrame')

        ttk.Label(f, text="Your Address", style='TLabel').pack(pady=(20, 5))
        self._addr_var = tk.StringVar(value="Loading...")
        addr_frame = ttk.Frame(f)
        addr_frame.pack(fill='x', padx=40)
        addr_entry = ttk.Entry(addr_frame, textvariable=self._addr_var, state='readonly',
                               font=('Consolas', 10))
        addr_entry.pack(fill='x', side='left', expand=True)
        ttk.Button(addr_frame, text="Copy",
                   command=lambda: self._copy_to_clipboard(self._addr_var.get())).pack(side='right', padx=5)

        ttk.Label(f, text="Balance", style='TLabel').pack(pady=(30, 5))
        self._balance_var = tk.StringVar(value="0.00000000 GAU")
        ttk.Label(f, textvariable=self._balance_var, style='Balance.TLabel').pack()

        ttk.Label(f, text="Recent Transactions", style='TLabel').pack(pady=(30, 5))
        self._tx_list = scrolledtext.ScrolledText(
            f, height=8, bg='#16213e', fg='#c0c0c0',
            font=('Consolas', 9), state='disabled', relief='flat'
        )
        self._tx_list.pack(fill='both', expand=True, padx=40, pady=10)

        ttk.Button(f, text="Refresh", command=self._refresh).pack(pady=5)

    def _build_send_tab(self):
        f = self._tab_send
        padx = 60

        ttk.Label(f, text="Send GAU", style='Title.TLabel').pack(pady=20)

        ttk.Label(f, text="Recipient Address:").pack(anchor='w', padx=padx)
        self._send_to_var = tk.StringVar()
        ttk.Entry(f, textvariable=self._send_to_var, width=60,
                  font=('Consolas', 10)).pack(fill='x', padx=padx, pady=5)

        ttk.Label(f, text="Amount (GAU):").pack(anchor='w', padx=padx)
        self._send_amt_var = tk.StringVar(value="0.0")
        ttk.Entry(f, textvariable=self._send_amt_var).pack(fill='x', padx=padx, pady=5)

        ttk.Label(f, text="Fee (GAU):").pack(anchor='w', padx=padx)
        self._send_fee_var = tk.StringVar(value="0.001")
        ttk.Entry(f, textvariable=self._send_fee_var).pack(fill='x', padx=padx, pady=5)

        ttk.Button(f, text="Send Transaction", command=self._do_send).pack(pady=20)

        self._send_status_var = tk.StringVar()
        ttk.Label(f, textvariable=self._send_status_var,
                  foreground='#00ff88', background='#1a1a2e').pack()

    def _build_explorer_tab(self):
        f = self._tab_explorer

        ttk.Label(f, text="Blockchain Explorer", style='Title.TLabel').pack(pady=10)

        info_frame = ttk.Frame(f)
        info_frame.pack(fill='x', padx=20)
        self._chain_info_var = tk.StringVar(value="Loading...")
        ttk.Label(info_frame, textvariable=self._chain_info_var).pack()

        ttk.Label(f, text="Recent Blocks:").pack(anchor='w', padx=20, pady=(10, 0))
        self._block_list = scrolledtext.ScrolledText(
            f, height=15, bg='#16213e', fg='#c0c0c0',
            font=('Consolas', 9), state='disabled', relief='flat'
        )
        self._block_list.pack(fill='both', expand=True, padx=20, pady=5)

    def _load_wallet(self):
        try:
            from gaumo.wallet import Wallet
            if Path(self.wallet_path).exists():
                self.wallet = Wallet.load(self.wallet_path)
                self._addr_var.set(self.wallet.address)
            else:
                self.wallet = Wallet.generate()
                self.wallet.save(self.wallet_path)
                self._addr_var.set(self.wallet.address)
                messagebox.showinfo("New Wallet", f"New wallet created!\nAddress: {self.wallet.address}")
        except Exception as e:
            messagebox.showerror("Wallet Error", str(e))

    def _start_refresh(self):
        self._refresh()
        self.after(15000, self._start_refresh)

    def _refresh(self):
        threading.Thread(target=self._do_refresh, daemon=True).start()

    def _do_refresh(self):
        try:
            # Status
            with urllib.request.urlopen(f"{self.node_url}/status", timeout=5) as r:
                status = json.loads(r.read())
            self.after(0, lambda: self._status_var.set(
                f"Height: {status['height']} | Peers: {status['peers']}"
            ))

            # Balance
            if self.wallet:
                with urllib.request.urlopen(f"{self.node_url}/balance/{self.wallet.address}", timeout=5) as r:
                    bal = json.loads(r.read())
                self.after(0, lambda: self._balance_var.set(f"{bal['balance_gau']:.8f} GAU"))

            # Recent blocks
            with urllib.request.urlopen(f"{self.node_url}/chain?start=0&limit=10", timeout=5) as r:
                blocks = json.loads(r.read())

            block_text = ""
            for b in reversed(blocks[-10:]):
                block_text += (
                    f"#{b['index']:6d} | {b['block_hash'][:16]}... | "
                    f"txs={len(b['transactions'])} | diff={b.get('difficulty', '?')}\n"
                )
            self.after(0, lambda: self._update_text(self._block_list, block_text))
            self.after(0, lambda: self._chain_info_var.set(
                f"Height: {status['height']} | Difficulty: {status['difficulty']} | "
                f"Mempool: {status['mempool_size']} txs"
            ))

        except Exception as e:
            msg = str(e)
            self.after(0, lambda: self._status_var.set(f"Offline: {msg}"))

    def _update_text(self, widget, text):
        widget.configure(state='normal')
        widget.delete('1.0', tk.END)
        widget.insert(tk.END, text)
        widget.configure(state='disabled')

    def _copy_to_clipboard(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)

    def _do_send(self):
        if not self.wallet:
            messagebox.showerror("Error", "No wallet loaded")
            return

        recipient = self._send_to_var.get().strip()
        try:
            amount = float(self._send_amt_var.get())
            fee = float(self._send_fee_var.get())
        except ValueError:
            messagebox.showerror("Error", "Invalid amount or fee")
            return

        threading.Thread(
            target=self._submit_transaction,
            args=(recipient, amount, fee),
            daemon=True,
        ).start()

    def _submit_transaction(self, recipient, amount_gau, fee_gau):
        try:
            from gaumo.core.utxo import UTXOSet, UTXO
            from gaumo.wallet import Wallet

            # Get UTXOs
            with urllib.request.urlopen(
                f"{self.node_url}/utxos/{self.wallet.address}", timeout=5
            ) as r:
                utxo_list = json.loads(r.read())

            utxo_set = UTXOSet()
            for u in utxo_list:
                utxo_set.add(UTXO.from_dict(u))

            amount_sat = int(amount_gau * 1e8)
            fee_sat = int(fee_gau * 1e8)
            tx = self.wallet.create_transaction(recipient, amount_sat, fee_sat, utxo_set)

            req = urllib.request.Request(
                f"{self.node_url}/transaction",
                data=json.dumps(tx.to_dict()).encode(),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                result = json.loads(r.read())

            self.after(0, lambda: self._send_status_var.set(f"Sent! TX: {result['tx_hash'][:20]}..."))
        except Exception as e:
            err = str(e)
            self.after(0, lambda: messagebox.showerror("Send Error", err))


def launch_gui(node_url='http://localhost:8080', wallet_path='wallet.json'):
    app = GaumoApp(node_url=node_url, wallet_path=wallet_path)
    app.mainloop()


if __name__ == '__main__':
    launch_gui()
