from src.config import load_config
from src.optimizer import Optimizer
from src.utils import set_random_seed


if __name__ == "__main__":
    config = load_config(path="config.yml")
    set_random_seed(seed=config.seed)
    genetic_wheel = Optimizer(config=config)
    genetic_wheel.run()