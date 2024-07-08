import yaml




def evaluate_repetition():
        repeat = False
        indexed_inputs = {}
        for input_name, input_config in input_mapping.items():
            if input_config["indexed"]:
                repeat = True
                for value in input_config["value"]:
                    
                # indexed_inputs[input_name] = input_config["value"]
        
        return indexed_inputs




if __name__ == "__main__":
    input_mapping = yaml.safe_load("""
                            value: {type: direct, value: [10, 20, 30], indexed: true}
                            min: {type: direct, value: [9, 23, 24], indexed: true}
                            max: {type: direct, value: 29, indexed: false}""")

    print(input_mapping)
    indexed_inputs = evaluate_repetition()
    print(indexed_inputs)
    for name, value in indexed_inputs:
        