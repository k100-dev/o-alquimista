"""Compatibilidade para o antigo ponto de entrada."""

from o_alquimista.cli import main, write_json

__all__ = ["main", "write_json"]


if __name__ == "__main__":
    raise SystemExit(main())
