"""Discovery and explicit database-setup commands."""

import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('discover', add_help=False, help='Discover URLs from active indexes')
    commands.add_parser('setup-db', add_help=False, help='Create schema and seed indexes')
    args, remaining = parser.parse_known_args(argv)
    if args.command == 'discover':
        from scraper.discovery import main as discover
        return discover(remaining)
    from scraper.db.setup import main as setup
    return setup(remaining)


if __name__ == '__main__':
    raise SystemExit(main())
