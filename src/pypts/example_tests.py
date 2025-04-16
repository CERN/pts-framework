import logging

'''
This file contains a collection of example tests that can be used to develop the PTS framework.
'''

logger = logging.getLogger(__name__)

some_value = 5

def test_to_run(target):
    # with nidmm.Session("Dev1") as session:
    #     print("Measurement: " + str(session.read()))
    # logger.info(f"I received {target}.")
    return {"compare": target == 45, "other_output": "abc"}

def other_test():
    # logger.info("I could also do this.")
    return {"some_return": True, "value": 3}

def simple_return():
    return (5, 4)

def range_test(value, min, max):
    # time.sleep(1)
    return {"compare": min < value < max}

def generate_error():
    raise AttributeError

def simple_output(value):
    return {"my_output": value + 1}


