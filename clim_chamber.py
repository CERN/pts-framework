

from time import sleep

current_temperature = 20
current_humidity = 50


def calculate_chamber_steps(t_steps, t_step, t_min, rh_steps, rh_step, rh_min):
    temperatures = []
    humidities = []
    for i in range(t_steps):
        for j in range(rh_steps):
            temperatures.append(t_min + i * t_step)
            humidities.append(rh_min + j * rh_step)
    return {"temperatures": temperatures, "humidities": humidities}

def wait_for_target(temperature, humidity):
    global current_temperature, current_humidity
    while current_temperature != temperature or current_humidity != humidity:
        print(f"Current temperature: {current_temperature} - Current humidity: {current_humidity}")
        if current_temperature < temperature:
            current_temperature += 1
        elif current_temperature > temperature:
            current_temperature -= 1
        if current_humidity < humidity:
            current_humidity += 1
        elif current_humidity > humidity:
            current_humidity -= 1
        sleep(1)
    return {}