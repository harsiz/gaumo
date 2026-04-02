"""
Command-line interface for Gaumo node.
"""
import argparse
import json
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)


def get_blockchain():
    from gaumo.core import Blockchain
    return Blockchain()


def cmd_wallet_new(args):
    from gaumo.wallet import Wallet
    path = args.output
    if not path:
        answer = input("Where do you want to save this wallet? [wallet.json]: ").strip()
        path = answer if answer else 'wallet.json'
    if Path(path).exists() and not args.force:
        print(f"Error: '{path}' already exists. Use --force to overwrite (THIS WILL DELETE YOUR FUNDS).")
        sys.exit(1)
    w = Wallet.generate()
    w.save(path)
    print(f"New wallet created:")
    print(f"  Address : {w.address}")
    print(f"  WIF     : {w.wif}")
    print(f"  Saved to: {path}")


def cmd_wallet_info(args):
    from gaumo.wallet import Wallet
    w = Wallet.load(args.wallet)
    print(f"Address : {w.address}")
    print(f"WIF     : {w.wif}")
    print(f"PubKey  : {w.public_key.hex()}")


def cmd_balance(args):
    import urllib.request
    url = f"http://{args.node}/balance/{args.address}"
    try:
        with urllib.request.urlopen(url) as r:
            data = json.loads(r.read())
        print(f"Address : {data['address']}")
        print(f"Balance : {data['balance_gau']:.8f} GAU")
        print(f"Satoshi : {data['balance']}")
    except Exception as e:
        print(f"Error: {e}")


def cmd_send(args):
    import urllib.request
    from gaumo.wallet import Wallet
    from gaumo.core import Blockchain, UTXOSet

    # Load wallet
    w = Wallet.load(args.wallet)

    # Get UTXOs from API
    url_utxos = f"http://{args.node}/utxos/{w.address}"
    try:
        with urllib.request.urlopen(url_utxos) as r:
            utxo_list = json.loads(r.read())
    except Exception as e:
        print(f"Failed to fetch UTXOs: {e}")
        return

    from gaumo.core.utxo import UTXOSet, UTXO
    utxo_set = UTXOSet()
    for u in utxo_list:
        utxo_set.add(UTXO.from_dict(u))

    amount_sat = int(float(args.amount) * 1e8)
    fee_sat = int(float(args.fee) * 1e8)

    try:
        tx = w.create_transaction(args.recipient, amount_sat, fee_sat, utxo_set)
    except ValueError as e:
        print(f"Transaction error: {e}")
        return

    # Submit to API
    tx_data = json.dumps(tx.to_dict()).encode()
    req = urllib.request.Request(
        f"http://{args.node}/transaction",
        data=tx_data,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req) as r:
            result = json.loads(r.read())
        print(f"Transaction submitted: {result['tx_hash']}")
    except Exception as e:
        print(f"Failed to submit: {e}")


def cmd_status(args):
    import urllib.request
    url = f"http://{args.node}/status"
    try:
        with urllib.request.urlopen(url) as r:
            data = json.loads(r.read())
        print(f"Height     : {data['height']}")
        print(f"Last Hash  : {data['last_block_hash'][:20]}...")
        print(f"Peers      : {data['peers']}")
        print(f"Mempool    : {data['mempool_size']} txs")
        print(f"Difficulty : {data['difficulty']}")
    except Exception as e:
        print(f"Error: {e}")


def cmd_mine(args):
    """Start mining on this node."""
    from gaumo.core import Blockchain
    from gaumo.mining import Miner
    from gaumo.net import Node
    from gaumo.api import APIServer
    from gaumo.wallet import Wallet
    import signal

    # Load or create wallet
    wallet_path = args.wallet or 'wallet.json'
    if Path(wallet_path).exists():
        w = Wallet.load(wallet_path)
    else:
        w = Wallet.generate()
        w.save(wallet_path)
        print(f"New wallet created: {w.address}")

    print(f"Mining address: {w.address}")

    blockchain = Blockchain()
    node = Node(blockchain, seeds=_parse_seeds(args.seeds))
    api = APIServer(blockchain, node, port=args.api_port)

    def on_block(block):
        print(f"\n[BLOCK FOUND] #{block.index} hash={block.block_hash[:20]}...")
        node.broadcast_block(block)

    miner = Miner(blockchain, w.address, on_block_found=on_block)

    node.start()
    api.start()

    print(f"API server: http://0.0.0.0:{args.api_port}")

    # Wait for initial chain sync before mining.
    # Keep waiting as long as height is still increasing (actively syncing).
    # Give up after 120s max in case we're offline / no peers.
    print("Syncing chain from peers...")
    MAX_SYNC_WAIT = 120
    STABLE_SECONDS = 4   # height must be unchanged for this many seconds to be "done"
    last_height = -1
    stable_count = 0
    for i in range(MAX_SYNC_WAIT):
        time.sleep(1)
        current_height = blockchain.height
        peers = node.get_peer_count()
        print(f"\r  Height: {current_height} | Peers: {peers} | Elapsed: {i+1}s  ", end='', flush=True)

        if peers == 0 and i >= 5:
            # No peers after 5s — just start on local chain
            break

        if current_height == last_height:
            stable_count += 1
            if stable_count >= STABLE_SECONDS and peers > 0:
                break  # height hasn't moved for STABLE_SECONDS — we're synced
        else:
            stable_count = 0  # still receiving blocks, reset counter

        last_height = current_height

    print(f"\nSynced to height {blockchain.height}. Starting miner...")

    miner.start()

    def _stop(sig, frame):
        print("\nStopping...")
        miner.stop()
        node.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _stop)

    try:
        while True:
            time.sleep(10)
            stats = miner.get_stats()
            print(
                f"[Stats] Height={blockchain.height} | "
                f"Rate={stats['hash_rate']:,.0f} H/s | "
                f"Hashes={stats['total_hashes']:,} | "
                f"Blocks={stats['blocks_found']} | "
                f"Peers={node.get_peer_count()}"
            )
    except KeyboardInterrupt:
        miner.stop()
        node.stop()


def cmd_node(args):
    """Run a node without mining."""
    from gaumo.core import Blockchain
    from gaumo.net import Node
    from gaumo.api import APIServer
    import signal

    blockchain = Blockchain()
    node = Node(blockchain, seeds=_parse_seeds(args.seeds),
                listen_port=args.listen_port)
    api = APIServer(blockchain, node, port=args.api_port)

    node.start()
    api.start()

    print(f"Node started. API: http://0.0.0.0:{args.api_port}")

    # Sync chain from peers before serving
    print("Syncing chain from peers...")
    MAX_SYNC_WAIT = 120
    STABLE_SECONDS = 4
    last_height = -1
    stable_count = 0
    for i in range(MAX_SYNC_WAIT):
        time.sleep(1)
        current_height = blockchain.height
        peers = node.get_peer_count()
        print(f"\r  Height: {current_height} | Peers: {peers} | Elapsed: {i+1}s  ", end='', flush=True)
        if peers == 0 and i >= 5:
            break
        if current_height == last_height:
            stable_count += 1
            if stable_count >= STABLE_SECONDS and peers > 0:
                break
        else:
            stable_count = 0
        last_height = current_height
    print(f"\nSynced to height {blockchain.height}.")
    print("Press Ctrl+C to stop.")

    def _stop(sig, frame):
        node.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _stop)

    try:
        while True:
            time.sleep(30)
            print(f"[Node] Height={blockchain.height} | Peers={node.get_peer_count()} | Mempool={blockchain.mempool.size()}")
    except KeyboardInterrupt:
        node.stop()


def cmd_peers(args):
    import urllib.request
    url = f"http://{args.node}/peers"
    try:
        with urllib.request.urlopen(url) as r:
            peers = json.loads(r.read())
        if peers:
            for p in peers:
                print(f"  {p['host']}:{p['port']} height={p.get('height', '?')}")
        else:
            print("No peers connected")
    except Exception as e:
        print(f"Error: {e}")


def cmd_mempool(args):
    import urllib.request
    url = f"http://{args.node}/mempool"
    try:
        with urllib.request.urlopen(url) as r:
            txs = json.loads(r.read())
        print(f"{len(txs)} transaction(s) in mempool:")
        for tx in txs:
            print(f"  {tx['tx_hash'][:20]}... outputs={len(tx['outputs'])}")
    except Exception as e:
        print(f"Error: {e}")


def cmd_gui(args):
    """Launch the Gaumo wallet GUI."""
    from gaumo.gui import launch_gui
    node_url = f"http://{args.node}"
    launch_gui(node_url=node_url, wallet_path=args.wallet)


def cmd_open(args):
    """Open the Gaumo directory in file explorer."""
    import subprocess
    import gaumo
    path = Path(gaumo.__file__).parent.parent
    if sys.platform == 'win32':
        subprocess.Popen(['explorer', str(path)])
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', str(path)])
    else:
        subprocess.Popen(['xdg-open', str(path)])
    print(f"Opened: {path}")


def _parse_seeds(seeds_arg) -> list:
    if not seeds_arg:
        return []
    result = []
    for s in seeds_arg.split(','):
        s = s.strip()
        if ':' in s:
            host, port = s.rsplit(':', 1)
            result.append((host, int(port)))
    return result


def main():
    parser = argparse.ArgumentParser(prog='gaumo', description='Gaumo (GAU) Cryptocurrency')
    parser.add_argument('--node', default='localhost:8080', help='API node address')
    sub = parser.add_subparsers(dest='command')

    # wallet new
    p = sub.add_parser('wallet-new', help='Generate a new wallet')
    p.add_argument('--output', help='Output file path (default: wallet.json)')
    p.add_argument('--force', action='store_true', help='Overwrite existing wallet file')

    # wallet info
    p = sub.add_parser('wallet-info', help='Show wallet information')
    p.add_argument('--wallet', required=True, help='Wallet file path')

    # balance
    p = sub.add_parser('balance', help='Check address balance')
    p.add_argument('address', help='Gaumo address')

    # send
    p = sub.add_parser('send', help='Send GAU')
    p.add_argument('recipient', help='Recipient address')
    p.add_argument('amount', type=float, help='Amount in GAU')
    p.add_argument('--fee', type=float, default=0.001, help='Fee in GAU (default: 0.001)')
    p.add_argument('--wallet', default='wallet.json', help='Wallet file')

    # status
    p = sub.add_parser('status', help='Show node status')

    # mine
    p = sub.add_parser('mine', help='Start mining')
    p.add_argument('--wallet', help='Wallet file')
    p.add_argument('--api-port', type=int, default=8080, help='API port')
    p.add_argument('--seeds', default='vps.justharsiz.lol:8765', help='Seed nodes (host:port,...)')

    # node
    p = sub.add_parser('node', help='Run a node (no mining)')
    p.add_argument('--api-port', type=int, default=8080, help='API port')
    p.add_argument('--listen-port', type=int, default=None, help='P2P listen port (optional)')
    p.add_argument('--seeds', default='vps.justharsiz.lol:8765', help='Seed nodes (host:port,...)')

    # peers
    p = sub.add_parser('peers', help='List connected peers')

    # mempool
    p = sub.add_parser('mempool', help='Show mempool')

    # gui
    p = sub.add_parser('gui', help='Open the Gaumo wallet GUI')
    p.add_argument('--wallet', default='wallet.json', help='Wallet file to load')

    # open file explorer
    sub.add_parser('.', help='Open Gaumo folder in file explorer')

    args = parser.parse_args()

    commands = {
        'wallet-new': cmd_wallet_new,
        'wallet-info': cmd_wallet_info,
        'balance': cmd_balance,
        'send': cmd_send,
        'status': cmd_status,
        'mine': cmd_mine,
        'node': cmd_node,
        'peers': cmd_peers,
        'mempool': cmd_mempool,
        'gui': cmd_gui,
        '.': cmd_open,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
