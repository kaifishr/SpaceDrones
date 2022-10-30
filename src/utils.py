"""Script with helper functions."""
import random

import numpy
import pygame


def set_random_seed(seed: int = 0) -> None:
    """Sets random seed."""
    random.seed(seed)
    numpy.random.seed(seed)


def capture_screen(screen, iteration: int) -> None:
    """Captures screen every simulation step.

    Args:
        screen:
        iteration:

    Returns:
        None
    """
    filename = f"screen_{iteration}"
    pygame.image.save(screen, filename)
