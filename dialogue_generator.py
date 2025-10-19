
import random

from entity import Actor



class ConversationNode:
    def __init__(self, context: list = [], mood: str = "Neutral" ):
        self.context = []
        self.mood = "Neutral"


    def generate_dialogue(self, character: Actor = None, context = None, mood: str = "Neutral"):
        self.character = character
        self.context = context if context is not None else []
        self.mood = mood

        if self.character.opinion >= 66:
            self.mood = "Friendly"
        elif self.character.opinion <= 33:
            self.mood = "Hostile"
        
        # Convert context to list if it's a string
        if isinstance(self.context, str):
            if self.context == "None":
                self.context = []
            else:
                self.context = [self.context]
        
        # Check for context keywords in the list
        context_str = " ".join(self.context) if self.context else ""

        # Generate response based on context and mood
        # KEY:
        # Identity: Asking for name/identity
        # Location: Asking for location
        # Response: NPC has already responded
        # Greeting: Initial greeting


        if "Greeting" in context_str:
            if self.mood == "Neutral":
                responses = {
                    "Greeting":[
                        "Hello there.",
                        "Greetings.",
                        "Well met.",
                        "Welcome.",
                        "Ah, greetings.",
                        "Ah, a friendly face.",
                    ]}
                return random.choice(responses["Greeting"]), ["Response"]

        if "Identity" in context_str:
            if self.mood == "Neutral":
                responses = {
                    "Identity":[
                        "I am called " + self.character.knowledge.get("name") + ".",
                        "My name is " + self.character.knowledge.get("name") + ".",
                        "They call me " + self.character.knowledge.get("name") + ".",
                        "You can call me " + self.character.knowledge.get("name") + ".",
                        "That would be " + self.character.knowledge.get("name") + ".",
                        "I go by " + self.character.knowledge.get("name") + ".",
                    ]}
                return random.choice(responses["Identity"]), ["Response", "Identity"]
        if "Goodbye" in context_str:
            if self.mood == "Neutral":
                responses = {
                    "Response":[
                        "Hello again.",
                        "Yes?",
                        "Hello there.",
                        "What do you need?",
                        "Oh, it's you again.",
                        "Yes, what is it?",
                        "What now?",
                        "We were just talking.",
                    ]
                }
                return random.choice(responses["Response"]), ["Response"]

        if "Response" in context_str:
            if self.mood == "Neutral":
                responses = {
                    "Response":[
                        "I've told you everything I know.",
                        "What more do you want to know?",
                        "Yes?",
                        "I know nothing more to share.",
                    ]}
                return random.choice(responses["Response"]), ["Response"]


        # Dictionary responses
        if "Where" in context_str or "Location" in context_str:
            if self.mood == "Neutral":
                responses = {
                    "Location":[
                        "This is " + self.character.knowledge.get("location", "a place") + ".",
                        "You are in " + self.character.knowledge.get("location", "a place") + ".",
                        "We are in " + self.character.knowledge.get("location", "a place") + ".",
                        "This place is called " + self.character.knowledge.get("location", "a place") + ".",
                        "This area is known as " + self.character.knowledge.get("location", "a place") + ".",
                    ]
                }
                return random.choice(responses["Location"]), ["Location"]
        # If context is empty list or "None" string
        elif not self.context or self.context == "None":
            if self.mood == "Neutral":
                responses = {
                    "Opening":[
                        "Hello ",
                        "Greetings ",
                        "Well met, ",
                        "Welcome ",
                        "Ah, greetings, ",
                        "Ah, a friendly face, ",
                    ],
                    "Address":[
                        "traveler.",
                        "adventurer.",
                        "stranger.",
                        "friend.",
                        "wanderer.",
                        "wayfarer.",
                    ],
                    "Closer":[
                        "",
                        "",
                        "",
                        "",
                        "",
                        " What can I do for you?",
                        " Welcome.",
                        f" Welcome to {self.character.knowledge.get('location', '')}."
                    ]
                }
                opening = random.choice(responses["Opening"])
                address = random.choice(responses["Address"])
                closer = random.choice(responses["Closer"])
                self.context = ["Response"]

                return (f"{opening}{address}{closer}", ["Response"])
        
        # Fallback if no conditions are met
        return ("I have nothing to say right now.", ["Default"])