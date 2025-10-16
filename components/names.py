
import random

def get_names(type:str="Human") -> str:
    if type == "Human":
        first_name = random.choice(
            [
                "Bob", "Doug", "Test", "Idiot"
            ]
        )
        last_name = random.choice(
            [
                "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis"
            ]
        )
    return f"{first_name} {last_name}"