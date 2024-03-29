"""Contains drone definition."""
import copy
import math

from Box2D import b2FixtureDef
from Box2D import b2PolygonShape
from Box2D.Box2D import b2World
from Box2D.Box2D import b2Vec2
from Box2D.Box2D import b2Filter
import numpy

from src.utils.config import Config
from src.drone.engine import Engines
from src.drone.raycast import RayCastCallback
from src.drone.model import load_model


class Agent:
    """Agent base class."""

    TIME_STEP = 0.0167

    def __init__(self) -> None:
        """Initializes class."""


class Drone(Agent):
    """Drone class.

    A drone consists of a body with four boosters attached.
    """

    vertices = [
        (0.5, 0.5),
        (-0.5, 0.5),
        (-0.5, -0.5),
        (0.5, -0.5),
    ]

    num_engines = 4

    def __init__(self, world: b2World, config: Config) -> None:
        """Initializes the wheel class."""
        super().__init__()

        self.world = world
        self.config = config

        # Initialize drone body
        rx_init = config.env.drone.init_position.x
        ry_init = config.env.drone.init_position.y
        self.init_position = b2Vec2(rx_init, ry_init)

        vx_init = config.env.drone.init_linear_velocity.x
        vy_init = config.env.drone.init_linear_velocity.y
        self.init_linear_velocity = b2Vec2(vx_init, vy_init)

        self.init_angular_velocity = config.env.drone.init_angular_velocity
        self.init_angle = (config.env.drone.init_angle * math.pi) / 180.0

        self.body = world.CreateDynamicBody(
            bullet=False,
            allowSleep=False,
            position=self.init_position,
            linearVelocity=self.init_linear_velocity,
            angularVelocity=self.init_angular_velocity,
            angle=self.init_angle,
            fixedRotation=True,
        )

        self.diam = config.env.drone.diam
        vertices = [(self.diam * x, self.diam * y) for (x, y) in self.vertices]

        fixture_def = b2FixtureDef(
            shape=b2PolygonShape(vertices=vertices),
            density=config.env.drone.density,
            friction=config.env.drone.friction,
            filter=b2Filter(groupIndex=-1),
        )
        self.body.CreateFixture(fixture_def)

        # Engines
        self.engine = Engines(body=self.body, config=config)
        self.max_force = config.env.drone.engine.max_force

        # Raycasting
        ray_length = config.env.drone.raycasting.ray_length

        # Define direction for raycasting in which we look for obstacles.
        self.points = [
            b2Vec2(ray_length, 0.0),
            b2Vec2(0.0, ray_length),
            b2Vec2(-ray_length, 0.0),
            b2Vec2(0.0, -ray_length),
            b2Vec2(ray_length, ray_length),
            b2Vec2(-ray_length, ray_length),
            b2Vec2(-ray_length, -ray_length),
            b2Vec2(ray_length, -ray_length),
        ]

        # Collision threshold
        d = self.diam
        h = self.engine.height
        w = self.engine.width_max
        self.collision_threshold = 1.2 * ((0.5 * d + h) ** 2 + (0.5 * w) ** 2) ** 0.5

        # Neural Network
        self.model = load_model(config=config)

        # Forces predicted by neural network.
        # Initialized with 0 for each engine.
        self.forces = [0.0 for _ in range(self.num_engines)]

        # Ray casting rendering
        self.callbacks = []
        self.p1 = []
        self.p2 = []

        # Input data for neural network
        self.data = []

        # Compute scalars for data normalization.
        x_min = config.env.domain.limit.x_min
        x_max = config.env.domain.limit.x_max
        y_min = config.env.domain.limit.y_min
        y_max = config.env.domain.limit.y_max
        domain_diam_x = x_max - x_min
        domain_diam_y = y_max - y_min
        domain_diagonal = (domain_diam_x**2 + domain_diam_y**2) ** 0.5
        domain_diameter = max(domain_diam_x, domain_diam_y)
        self.normalize_diag = 1.0 / domain_diagonal
        self.normalize_diam = 1.0 / (0.5 * domain_diameter)
        self.normalize_velocity = 0.1

        # Fitness score
        self.score = 0.0
        self.theta_old = None
        self.speed_old_x = None
        self.speed_old_y = None
        self.pos_old_x = None
        self.pos_old_y = None

    def comp_score(self) -> None:
        """Computes current fitness score.

        Accumulates drone's linear velocity over one generation.
        This effectively computes the distance traveled by the
        drone over time divided by the simulation's step size.
        """
        if self.body.active:
            score = 0

            # Reward: Distance to target
            if self.config.optimizer.reward.distance_to_target:
                position_agent = self.body.position
                position_target = self.world.target.body.position
                dist_x = position_agent.x - position_target.x
                dist_y = position_agent.y - position_target.y
                distance = (dist_x**2 + dist_y**2) ** 0.5
                score += 1.0 / (1.0 + distance**2)
                self.score += score

            # Reward distance traveled.
            if self.config.optimizer.reward.distance:
                phi = 0.1
                velocity = self.body.linearVelocity
                speed = (velocity.x**2 + velocity.y**2) ** 0.5
                distance = self.TIME_STEP * speed
                self.score += phi * distance

    def fetch_data(self):
        """Fetches data from drone for neural network."""

        if self.body.active:
            # Add distance to obstacles to input data
            # Uses ray casting to measure distance to domain walls.
            self.p1.clear()
            self.p2.clear()
            self.callbacks.clear()
            self.data.clear()

            p1 = self.body.position

            for point in self.points:
                # Perform ray casting from drone position p1 to to point p2.
                p2 = p1 + self.body.GetWorldVector(localVector=point)
                cb = RayCastCallback()
                self.world.RayCast(cb, p1, p2)

                # Save ray casting data for rendering.
                self.p1.append(copy.copy(p1))
                self.p2.append(copy.copy(p2))
                self.callbacks.append(copy.copy(cb))

                # Gather distance data.
                if cb.hit:
                    # When the ray has hit something compute distance
                    # from drone to obstacle from raw features.
                    diff = cb.point - p1
                    dist = (diff.x**2 + diff.y**2) ** 0.5
                    self.data.append(dist * self.normalize_diag)
                else:
                    self.data.append(-1.0)

            # Add position and velocity of agent to input data
            for pos in self.body.position:
                self.data.append(pos * self.normalize_diam)

            for vel in self.body.linearVelocity:
                self.data.append(vel * self.normalize_velocity)

            # Position to target:
            for pos in self.world.target.body.position:
                self.data.append(pos * self.normalize_diam)

    def detect_collision(self):
        """Detects collision with objects.

        Here we use ray casting information here and speak of a collision
        when an imaginary circle with the total diameter of the drone
        touches another object.
        """
        if self.body.active:
            for p1, cb in zip(self.p1, self.callbacks):
                if cb.hit:
                    diff = cb.point - p1
                    dist = (diff.x**2 + diff.y**2) ** 0.5
                    if dist < self.collision_threshold:
                        self.body.active = False
                        self.forces = self.num_engines * [0.0]
                        self.callbacks.clear()
                        self.p1.clear()
                        self.p2.clear()
                        break

    def comp_action(self) -> None:
        """Computes next section of actions applied to engines.

        Next steps of action are computed by feeding obstacle data coming
        from ray casting to the drone's neural network which then returns
        a set of actions (forces) to be applied to the drone's engines.
        """
        if self.body.active:
            force_pred = self.model.forward(self.data)
            self.forces = self.max_force * force_pred

    def apply_action(self, noise: float = None) -> None:
        """Applies force to Drone coming from neural network.

        Args:
            noise: Amount of noise added to action. Default: None

        Each engine is controlled individually.
        """
        body = self.body

        forces = numpy.array(self.forces)

        if noise:
            noise = numpy.random.normal(loc=0.0, scale=noise, size=forces.shape)
            forces += noise

        if body.active:
            f_left, f_right, f_up, f_down = forces

            # Left
            f = body.GetWorldVector(localVector=b2Vec2(f_left, 0.0))
            p = body.GetWorldPoint(localPoint=b2Vec2(-0.5 * self.diam, 0.0))
            body.ApplyForce(f, p, True)

            # Right
            f = body.GetWorldVector(localVector=b2Vec2(-f_right, 0.0))
            p = body.GetWorldPoint(localPoint=b2Vec2(0.5 * self.diam, 0.0))
            body.ApplyForce(f, p, True)

            # Up
            f = body.GetWorldVector(localVector=b2Vec2(0.0, -f_up))
            p = body.GetWorldPoint(localPoint=b2Vec2(0.0, 0.5 * self.diam))
            body.ApplyForce(f, p, True)

            # Down
            f = body.GetWorldVector(localVector=b2Vec2(0.0, f_down))
            p = body.GetWorldPoint(localPoint=b2Vec2(0.0, 0.5 * self.diam))
            body.ApplyForce(f, p, True)
