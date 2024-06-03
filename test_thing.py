import logging

logger = logging.getLogger(__name__)

def test_to_run(target):
    logger.info(f"I received {target}.")
    return {"pass": target == 42}

def other_test(value):
    logger.info("I could also do this.")
    return {"pass": True, "value": value}
