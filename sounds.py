import pygame
import random

pygame.mixer.init()

quaff_sound = pygame.mixer.Sound("RP/sfx/quaff.wav")
death_sound = pygame.mixer.Sound("RP/sfx/death.wav")
door_open_sound = pygame.mixer.Sound("RP/sfx/door_open.wav")
door_close_sound = pygame.mixer.Sound("RP/sfx/door_close.wav")
stairs_sound = pygame.mixer.Sound("RP/sfx/stairs.wav")
darkness_spawn_sound = pygame.mixer.Sound("RP/sfx/darkness_spawn.wav")
chest_open_sound = pygame.mixer.Sound("RP/sfx/chest_open.wav")
pull_torch_sound = pygame.mixer.Sound("RP/sfx/fire_pull.wav")
lightning_sound = pygame.mixer.Sound("RP/sfx/lightning_sound.wav")
confusion_sound = pygame.mixer.Sound("RP/sfx/confusion_cast.wav")
pickup_coin_sound = pygame.mixer.Sound("RP/sfx/pickup_coin.wav")
level_up_sound = pygame.mixer.Sound("RP/sfx/level_up.wav")
torch_burns_out_sound = pygame.mixer.Sound("RP/sfx/burn_out.wav")

def play_transfer_item_sound():
    transfer_item_sounds = [
        pygame.mixer.Sound("RP/sfx/transfer/transfer.wav"),
        pygame.mixer.Sound("RP/sfx/transfer/transfer2.wav"),
        pygame.mixer.Sound("RP/sfx/transfer/transfer3.wav"),
        pygame.mixer.Sound("RP/sfx/transfer/transfer4.wav"),
    ]
    sound = random.choice(transfer_item_sounds)
    sound.play()

def play_walk_sound():
    if random.random() < 0.5:
        return  # 50% chance to not play a sound for variety
    walk_sounds = [
        pygame.mixer.Sound("RP/sfx/walk/walk1.wav"),
        pygame.mixer.Sound("RP/sfx/walk/walk2.wav"),
        pygame.mixer.Sound("RP/sfx/walk/walk3.wav"),
        pygame.mixer.Sound("RP/sfx/walk/walk4.wav"),
        pygame.mixer.Sound("RP/sfx/walk/walk5.wav"),
    ]
    sound = random.choice(walk_sounds)
    sound.play()
    
def play_attack_sound():
    attack_sounds = [
        pygame.mixer.Sound("RP/sfx/hit/hit1.wav"),
        pygame.mixer.Sound("RP/sfx/hit/hit2.wav"),
        pygame.mixer.Sound("RP/sfx/hit/hit3.wav"),
        pygame.mixer.Sound("RP/sfx/hit/hit4.wav"),
    ]
    sound = random.choice(attack_sounds)
    sound.play()