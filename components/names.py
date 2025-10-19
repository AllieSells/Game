
import random
from shlex import join

def get_location_name(type:str="Village") -> str:
    if type == "Village":
        options = {
            "prefixes": [
                "Silver", "Gold", "Iron", "Dragon", "Shadow", "Storm",
                "Raven", "Wolf", "Eagle", "Lion", "Crystal", "Sun",
                "Fire", "Frost", "Thunder",
                "Yorm", "N'thal", "Kal", "Zan", "Vor", "Xan", "Qir",
                "Dra", "Mor", "Bel", "Tal", "Kor", "Fen", "Gar",
                "Stone", "River", "Lizard", "Pebble", "Rock", "Stone",
                "Elin", "Falin", "Gorin", "Halin", "Irin", "Jorin",
                "Korin", "Lorin", "Morin", "Nalin", "Orin", "Porin",
                "Water", "Breeze", "Cave", "Dark", "Ember", "Light",
                "Hell", "Yor", "Gratta", "Lalo", "Mira", "Nira", "Ossa",
                "Pira", "Quilla", "Rossa", "Sira", "Torra", "Ulla"
            ],
            "joiners": ["","", "", "", "", "-"],
            "suffixes": [
                "hold", "dale", "ford", "haven", "crest", "watch",
                "burg", "deep", "deep", "mouth", "shade", "view",
                "n'gall", "thar", "dell", "mere", "wick", "sial",
                "ton", "ville", "polis", "grad", "cairn", "port",
                "shire", "stead", "wick", "wynd", "wyn", "moor", "mere",
                "fall", "deep", "dark", "ridge", "rock", "den",
                "hollow", "fen", "spire", "uhntha", "yarth", "zalla",
                "quor", "vash", "loth", "dros", "gorn", "mash",
                "nash", "rath", "sorn", "tash", "vorn", "wath",
                "xath", "yash", "zorn", "thil", "dil", "sil", "ril", "mil", "bil",
            ]}
        prefix = random.choice(options["prefixes"])
        joiner = random.choice(options["joiners"])
        suffix = random.choice(options["suffixes"])
        return f"{prefix}{joiner}{suffix}"

def get_names(type:str="Human", gender:str="Androgynous") -> str:
    first_name = ""
    last_name = ""
    if type == "Human":
        if gender == "Male":
            first_name = random.choice([
    "Alaric", "Cedric", "Doran", "Edric", "Fendrel", "Garrick",
    "Harlan", "Joren", "Kendric", "Lorien", "Merrick", "Orin",
    "Percival", "Quentin", "Roland", "Theron", "Ulric", "Varen",
    "Wystan", "Baldric", "Duncan", "Eldon", "Faelan", "Gideon",
    "Hadrian", "Isidore", "Jareth", "Kael", "Lucan", "Magnus",
    "Nolan", "Orrin", "Phineas", "Roderic", "Soren", "Tobias",
    "Urian", "Valen", "Wendell", "Xander", "Yorick", "Zephan",
    "Alistair", "Brennan", "Cormac", "Darien", "Evander", "Finnian",
    "Garron", "Hector", "Icarus", "Jasper", "Kieran", "Leoric",
    "Malric", "Nivian", "Orven", "Peregrin", "Quillon", "Rafferty",
    "Sayer", "Tavian", "Ulfric", "Veylan", "Wyric", "Zared"
])
            last_name = random.choice([
    "Ashford", "Blackwood", "Cinderfell", "Duskbane", "Eldercrest", "Fairchild",
    "Grimsbane", "Hawthorne", "Ironwood", "Jorvath", "Kensington", "Larkspur",
    "Morningshadow", "Nettleford", "Oakheart", "Pendrake", "Quenwell", "Ravenwood",
    "Stormrider", "Thornfield", "Umbermoor", "Valemont", "Westbrook", "Yarwood",
    "Zephyrhill", "Briarwood", "Coldhollow", "Dragonspire", "Evenwood", "Frostfall",
    "Goldhaven", "Highcliff", "Ivoryhill", "Juniper", "Kingswell", "Lionshield",
    "Moonshadow", "Nightbreeze", "Oakenheart", "Proudmoore", "Quickwater", "Redgrove",
    "Silverbrook", "Tallspire", "Underwood", "Violetmoor", "Windrider", "Xanthera",
    "Youngblood", "Zephryns", "Brightwater", "Crowhurst", "Dunewalker", "Ebonvale",
    "Foxglove", "Glimmerfell", "Halloway"
])
        elif gender == "Female":
            first_name = random.choice([
    "Aeliana", "Brienne", "Caelia", "Daphne", "Elara", "Fiona",
    "Gwendolyn", "Helena", "Isolde", "Jasmin", "Kaela", "Liora",
    "Maris", "Nerissa", "Olwen", "Perin", "Quenessa", "Rosalind",
    "Selene", "Thera", "Ulani", "Vespera", "Willow", "Xylia",
    "Ysolde", "Zephyra", "Althea", "Brielle", "Celestine", "Danika",
    "Evelina", "Freyja", "Giselle", "Honora", "Isla", "Joriel",
    "Kiera", "Lyanna", "Mirelle", "Nadia", "Orla", "Petra",
    "Quilla", "Rhiannon", "Seraphine", "Thalassa", "Umbra", "Valeria",
    "Wynne", "Xandra", "Yara", "Zinnia", "Amara", "Beatrice",
    "Cerys", "Delphine", "Elowen", "Fiora", "Galadriel", "Hestia",
    "Imara", "Juliana", "Katrina", "Leona"
])
            last_name = random.choice([
    "Ashford", "Blackwood", "Cinderfell", "Duskbane", "Eldercrest", "Fairchild",
    "Grimsbane", "Hawthorne", "Ironwood", "Jorvath", "Kensington", "Larkspur",
    "Morningshadow", "Nettleford", "Oakheart", "Pendrake", "Quenwell", "Ravenwood",
    "Stormrider", "Thornfield", "Umbermoor", "Valemont", "Westbrook", "Yarwood",
    "Zephyrhill", "Briarwood", "Coldhollow", "Dragonspire", "Evenwood", "Frostfall",
    "Goldhaven", "Highcliff", "Ivoryhill", "Juniper", "Kingswell", "Lionshield",
    "Moonshadow", "Nightbreeze", "Oakenheart", "Proudmoore", "Quickwater", "Redgrove",
    "Silverbrook", "Tallspire", "Underwood", "Violetmoor", "Windrider", "Xanthera",
    "Youngblood", "Zephryns", "Brightwater", "Crowhurst", "Dunewalker", "Ebonvale",
    "Foxglove", "Glimmerfell", "Halloway"
])
        else:  # Androgynous or unspecified
            first_name = random.choice([
                    "Aeliana", "Brienne", "Caelia", "Daphne", "Elara", "Fiona",
    "Gwendolyn", "Helena", "Isolde", "Jasmin", "Kaela", "Liora",
    "Maris", "Nerissa", "Olwen", "Perin", "Quenessa", "Rosalind",
    "Selene", "Thera", "Ulani", "Vespera", "Willow", "Xylia",
    "Ysolde", "Zephyra", "Althea", "Brielle", "Celestine", "Danika",
    "Evelina", "Freyja", "Giselle", "Honora", "Isla", "Joriel",
    "Kiera", "Lyanna", "Mirelle", "Nadia", "Orla", "Petra",
    "Quilla", "Rhiannon", "Seraphine", "Thalassa", "Umbra", "Valeria",
    "Wynne", "Xandra", "Yara", "Zinnia", "Amara", "Beatrice",
    "Cerys", "Delphine", "Elowen", "Fiora", "Galadriel", "Hestia",
    "Imara", "Juliana", "Katrina", "Leona",
    "Alaric", "Cedric", "Doran", "Edric", "Fendrel", "Garrick",
    "Harlan", "Joren", "Kendric", "Lorien", "Merrick", "Orin",
    "Percival", "Quentin", "Roland", "Theron", "Ulric", "Varen",
    "Wystan", "Baldric", "Duncan", "Eldon", "Faelan", "Gideon",
    "Hadrian", "Isidore", "Jareth", "Kael", "Lucan", "Magnus",
    "Nolan", "Orrin", "Phineas", "Roderic", "Soren", "Tobias",
    "Urian", "Valen", "Wendell", "Xander", "Yorick", "Zephan",
    "Alistair", "Brennan", "Cormac", "Darien", "Evander", "Finnian",
    "Garron", "Hector", "Icarus", "Jasper", "Kieran", "Leoric",
    "Malric", "Nivian", "Orven", "Peregrin", "Quillon", "Rafferty",
    "Sayer", "Tavian", "Ulfric", "Veylan", "Wyric", "Zared"
])
            last_name = random.choice([
    "Ashford", "Blackwood", "Cinderfell", "Duskbane", "Eldercrest", "Fairchild",
    "Grimsbane", "Hawthorne", "Ironwood", "Jorvath", "Kensington", "Larkspur",
    "Morningshadow", "Nettleford", "Oakheart", "Pendrake", "Quenwell", "Ravenwood",
    "Stormrider", "Thornfield", "Umbermoor", "Valemont", "Westbrook", "Yarwood",
    "Zephyrhill", "Briarwood", "Coldhollow", "Dragonspire", "Evenwood", "Frostfall",
    "Goldhaven", "Highcliff", "Ivoryhill", "Juniper", "Kingswell", "Lionshield",
    "Moonshadow", "Nightbreeze", "Oakenheart", "Proudmoore", "Quickwater", "Redgrove",
    "Silverbrook", "Tallspire", "Underwood", "Violetmoor", "Windrider", "Xanthera",
    "Youngblood", "Zephryns", "Brightwater", "Crowhurst", "Dunewalker", "Ebonvale",
    "Foxglove", "Glimmerfell", "Halloway"
])
    return f"{first_name} {last_name}"