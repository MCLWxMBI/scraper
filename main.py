"""Root collection entry point for local runs and GitHub Actions."""

from scraper.pipeline import main as collect_main


def main(argv: list[str] | None = None) -> int:
    return collect_main(argv)


if __name__ == '__main__':
    raise SystemExit(main())
