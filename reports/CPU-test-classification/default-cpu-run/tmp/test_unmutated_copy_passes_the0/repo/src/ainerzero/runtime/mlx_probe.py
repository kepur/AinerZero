"""A disposable process for read-only MLX readiness checks."""

import json


def main() -> int:
    try:
        import mlx.core as mx

        available = bool(mx.metal.is_available())
        details = {}
        if available:
            info = mx.device_info()
            for key in (
                "device_name",
                "architecture",
                "memory_size",
                "max_buffer_length",
                "max_recommended_working_set_size",
            ):
                if key in info:
                    details[key] = info[key]
        print(json.dumps({"available": available, "device": details, "checked": True}))
        return 0
    except Exception as exc:
        print(json.dumps({"available": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
