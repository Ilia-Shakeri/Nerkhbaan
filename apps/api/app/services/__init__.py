__all__ = ["AlertEngine", "DLQWorker", "PricingService"]


def __getattr__(name: str):
    if name == "AlertEngine":
        from .alert_engine import AlertEngine

        return AlertEngine
    if name == "DLQWorker":
        from .dlq_worker import DLQWorker

        return DLQWorker
    if name == "PricingService":
        from .pricing import PricingService

        return PricingService
    raise AttributeError(name)
