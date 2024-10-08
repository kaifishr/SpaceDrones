"""Optimizer class for genetic optimization."""

import time
from pathlib import Path

from tensorboardX import SummaryWriter

from src.environment import Environment
from src.optimizer import Optimizer
from src.utils.config import Config
from src.utils.utils import save_checkpoint


class Trainer:
    """Optimizer class.

    Optimizer uses genetic optimization.

    Attributes:
        config:
        env:
        writer:
    """

    def __init__(self, env: Environment, optimizer: Optimizer, config: Config) -> None:
        """Initializes Trainer"""
        self.env = env
        self.optimizer = optimizer
        self.config = config

        self.writer = SummaryWriter()

        # Save config file
        file_path = Path(self.writer.logdir) / "config.txt"
        with open(file_path, "w", encoding="utf-8") as file:
            file.write(self.config.__str__())

    def run(self) -> None:
        """Runs genetic optimization."""

        cfg = self.config

        num_max_steps = cfg.optimizer.num_max_steps
        step = 0
        generation = 0
        best_reward = 0.0

        time_start = time.time()
        self.env.reset()
        is_running = True

        while is_running:
            # Physics and rendering.
            self.env.step()

            # Fetch data for neural network.
            self.env.fetch_data()

            # Detect collisions with other bodies
            if not cfg.env.allow_collision_domain:
                self.env.collision_detection()

            # Run neural network prediction
            self.env.comp_action()

            # Apply network predictions to drone
            self.env.apply_action()

            # Compute current fitness of each drone
            self.env.comp_reward()

            # Select next target.
            self.env.next_target()

            # Method that run at end of simulation.
            if ((step + 1) % num_max_steps == 0) or self.env.is_done():
                self.optimizer.step()

                # Select fittest agent based on distance traveled.
                results = self.env.get_results()

                # Reset drones to start over again.
                self.env.reset()

                # Write stats to Tensorboard.
                for result_name, result_value in results.items():
                    if isinstance(result_value, float):
                        self.writer.add_scalar(
                            tag=result_name, 
                            scalar_value=result_value, 
                            global_step=generation,
                        )
                    elif isinstance(result_value, list):
                        self.writer.add_histogram(
                            tag=result_name, 
                            values=result_value, 
                            global_step=generation,
                        )
                self.writer.add_scalar("seconds_episode", time.time() - time_start, generation)

                # Save model
                if cfg.checkpoints.save_model:
                    if results["mean_reward"] > best_reward:
                        index = self.env.index_best_agent()
                        model = self.env.drones[index].model
                        save_checkpoint(model=model, config=cfg)
                        best_reward = results["mean_reward"]

                step = 0
                generation += 1
                print(f"{generation = }")

                time_start = time.time()

            step += 1
