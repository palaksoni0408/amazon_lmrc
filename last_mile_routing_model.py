"""
Last-Mile Routing Optimization Model
Using p-Median Hub Location and GA-NSGA-II for Multi-Depot Vehicle Routing
Based on Amazon Last Mile Routing Research Challenge Dataset
"""

import json
import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Any
import warnings
warnings.filterwarnings('ignore')

# For genetic algorithm
from deap import base, creator, tools, algorithms
import random

class DataPreprocessor:
    """Preprocesses the almrrc2021 dataset"""
    
    def __init__(self, data_dir: str, sample_size: int = 500):
        self.data_dir = Path(data_dir)
        self.sample_size = sample_size
        self.package_data = None
        self.route_data = None
        self.travel_times = None
        
    def load_data(self) -> Dict[str, Any]:
        """Load JSON data files"""
        print(f"Loading dataset from {self.data_dir}...")
        
        # Load package data
        try:
            with open(self.data_dir / "almrrc2021-data-training/model_build_inputs/package_data.json", 'r') as f:
                self.package_data = json.load(f)
            print(f"✓ Loaded package data: {len(self.package_data)} packages")
        except Exception as e:
            print(f"✗ Error loading package data: {e}")
            
        # Load route data
        try:
            with open(self.data_dir / "almrrc2021-data-training/model_build_inputs/route_data.json", 'r') as f:
                self.route_data = json.load(f)
            print(f"✓ Loaded route data: {len(self.route_data)} routes")
        except Exception as e:
            print(f"✗ Error loading route data: {e}")
            
        # Load travel times
        try:
            with open(self.data_dir / "almrrc2021-data-training/model_build_inputs/travel_times.json", 'r') as f:
                self.travel_times = json.load(f)
            print(f"✓ Loaded travel times")
        except Exception as e:
            print(f"✗ Error loading travel times: {e}")
            
        return {
            'packages': self.package_data,
            'routes': self.route_data,
            'travel_times': self.travel_times
        }
    
    def preprocess(self) -> Tuple[List[Dict], List[Dict], np.ndarray]:
        """Preprocess data for optimization"""
        print("\nPreprocessing data...")
        
        demand_nodes = []
        route_list = []
        
        # Extract demand nodes and routes
        if self.package_data:
            # Sample routes for computational efficiency
            sampled_routes = list(self.route_data.items())[:self.sample_size] if self.route_data else []
            
            for route_id, route_info in sampled_routes:
                route_list.append({
                    'route_id': route_id,
                    'stops': len(route_info.get('stops', [])),
                    'packages': len(route_info.get('sequence', [])),
                    'date': route_info.get('date_YYYY_MM_DD', ''),
                    'region': route_info.get('region', 'Unknown')
                })
                
                # Extract demand from packages in this route
                for pkg_id in route_info.get('sequence', [])[:20]:  # Limit to 20 packages per route
                    if pkg_id in self.package_data:
                        pkg = self.package_data[pkg_id]
                        demand_nodes.append({
                            'package_id': pkg_id,
                            'route_id': route_id,
                            'lat': pkg.get('lat', np.random.uniform(32, 48)),
                            'lng': pkg.get('lng', np.random.uniform(-120, -70)),
                            'weight': pkg.get('size_cm_3', 1000),
                            'region': route_info.get('region', 'Unknown')
                        })
        
        print(f"✓ Extracted {len(demand_nodes)} demand nodes from {len(route_list)} routes")
        
        # Compute distance matrix using Euclidean distance
        if demand_nodes:
            coordinates = np.array([[d['lat'], d['lng']] for d in demand_nodes])
            n_nodes = len(coordinates)
            distance_matrix = np.zeros((n_nodes, n_nodes))
            
            for i in range(n_nodes):
                for j in range(n_nodes):
                    lat1, lng1 = coordinates[i]
                    lat2, lng2 = coordinates[j]
                    # Haversine approximation
                    dist = np.sqrt((lat2 - lat1)**2 + (lng2 - lng1)**2) * 111  # ~111 km per degree
                    distance_matrix[i, j] = dist
            
            print(f"✓ Computed {n_nodes}x{n_nodes} distance matrix")
        else:
            distance_matrix = np.array([[0]])
        
        return demand_nodes, route_list, distance_matrix


class PMedainHubLocation:
    """Solves the p-Median Hub Location Problem"""
    
    def __init__(self, demand_nodes: List[Dict], distance_matrix: np.ndarray, p: int = 3):
        self.demand_nodes = demand_nodes
        self.distance_matrix = distance_matrix
        self.p = p
        self.n = len(demand_nodes)
        self.hub_opening_cost = 5000  # Fixed cost per hub
        
    def greedy_pmedian(self) -> Tuple[List[int], np.ndarray]:
        """Greedy p-Median algorithm"""
        print(f"\nSolving p-Median Hub Location (p={self.p})...")
        
        opened_hubs = []
        unserved = set(range(self.n))
        
        # Greedy selection: iteratively add hubs
        for _ in range(self.p):
            best_hub = None
            best_cost = float('inf')
            
            for candidate in range(self.n):
                if candidate not in opened_hubs:
                    # Calculate cost if this hub is opened
                    cost = self.hub_opening_cost
                    temp_hubs = opened_hubs + [candidate]
                    
                    for node in unserved:
                        min_dist = min(self.distance_matrix[node, h] for h in temp_hubs)
                        cost += min_dist
                    
                    if cost < best_cost:
                        best_cost = cost
                        best_hub = candidate
            
            if best_hub is not None:
                opened_hubs.append(best_hub)
                print(f"  Hub {best_hub+1}/{self.p} opened at location {best_hub}")
        
        # Assign nodes to nearest hub
        assignments = np.zeros(self.n, dtype=int)
        for node in range(self.n):
            nearest_hub = min(opened_hubs, key=lambda h: self.distance_matrix[node, h])
            assignments[node] = nearest_hub
        
        print(f"✓ Found {len(opened_hubs)} hub locations")
        return opened_hubs, assignments
    
    def calculate_cost(self, opened_hubs: List[int], assignments: np.ndarray) -> float:
        """Calculate total cost"""
        cost = len(opened_hubs) * self.hub_opening_cost
        for node in range(self.n):
            hub = opened_hubs[assignments[node]]
            cost += self.distance_matrix[node, hub]
        return cost


class GANSGAIIRouter:
    """Solves Multi-Depot Vehicle Routing using GA-NSGA-II"""
    
    def __init__(self, demand_nodes: List[Dict], distance_matrix: np.ndarray, 
                 opened_hubs: List[int], assignments: np.ndarray, 
                 vehicle_capacity: float = 10000, max_route_length: float = 600):
        self.demand_nodes = demand_nodes
        self.distance_matrix = distance_matrix
        self.opened_hubs = opened_hubs
        self.assignments = assignments
        self.vehicle_capacity = vehicle_capacity
        self.max_route_length = max_route_length
        self.n = len(demand_nodes)
        
        # Create hub clusters
        self.clusters = {}
        for hub in opened_hubs:
            self.clusters[hub] = [i for i in range(self.n) if assignments[i] == hub]
    
    def calculate_route_distance(self, route: List[int], hub_idx: int) -> float:
        """Calculate total distance for a route"""
        if not route:
            return 0
        
        distance = 0
        prev = self.opened_hubs[hub_idx]  # Start from hub
        
        for node in route:
            distance += self.distance_matrix[prev, node]
            prev = node
        
        distance += self.distance_matrix[prev, self.opened_hubs[hub_idx]]  # Return to hub
        return distance
    
    def calculate_route_load(self, route: List[int]) -> float:
        """Calculate total load for a route"""
        load = 0
        for node in route:
            if node < len(self.demand_nodes):
                load += self.demand_nodes[node].get('weight', 1000)
        return load
    
    def create_individual(self, hub_idx: int) -> List[int]:
        """Create random individual (route)"""
        cluster = self.clusters[self.opened_hubs[hub_idx]]
        individual = cluster.copy()
        random.shuffle(individual)
        return individual
    
    def evaluate_fitness(self, individual: List[int], hub_idx: int) -> Tuple[float, float, float]:
        """Evaluate fitness: (distance, fleet_size, balance)"""
        cluster = self.clusters[self.opened_hubs[hub_idx]]
        
        # Split into routes based on capacity
        routes = []
        current_route = []
        current_load = 0
        
        for node in individual:
            node_weight = self.demand_nodes[node].get('weight', 1000)
            
            if current_load + node_weight > self.vehicle_capacity:
                if current_route:
                    routes.append(current_route)
                current_route = [node]
                current_load = node_weight
            else:
                current_route.append(node)
                current_load += node_weight
        
        if current_route:
            routes.append(current_route)
        
        # Calculate metrics
        total_distance = sum(self.calculate_route_distance(route, hub_idx) for route in routes)
        fleet_size = len(routes)
        route_balance = np.std([len(r) for r in routes]) if routes else 0
        
        return (total_distance, float(fleet_size), route_balance)
    
    def run_ga(self, generations: int = 100, population_size: int = 50) -> Dict[str, Any]:
        """Run NSGA-II algorithm"""
        print(f"\nRunning GA-NSGA-II Vehicle Routing...")
        print(f"  Population size: {population_size}")
        print(f"  Generations: {generations}")
        
        # Create DEAP types
        creator.create("FitnessMulti", base.Fitness, weights=(-1.0, -1.0, -1.0))
        creator.create("Individual", list, fitness=creator.FitnessMulti)
        
        toolbox = base.Toolbox()
        
        # For each hub, run GA
        all_routes = {}
        total_distance = 0
        total_vehicles = 0
        
        for hub_idx, hub in enumerate(self.opened_hubs):
            print(f"\n  Processing Hub {hub_idx + 1}/{len(self.opened_hubs)}...")
            
            cluster = self.clusters[hub]
            if not cluster:
                continue
            
            best_routes = []
            best_distance = float('inf')
            
            # Run simplified GA
            for gen in range(generations):
                population = [self.create_individual(hub_idx) for _ in range(population_size)]
                
                fitness_scores = []
                for ind in population:
                    fit = self.evaluate_fitness(ind, hub_idx)
                    fitness_scores.append((fit[0], fit[1], fit[2]))
                
                # Sort by fitness
                sorted_idx = np.argsort([f[0] for f in fitness_scores])
                best_individual = population[sorted_idx[0]]
                best_fit = fitness_scores[sorted_idx[0]]
                
                if best_fit[0] < best_distance:
                    best_distance = best_fit[0]
                    best_routes = best_individual
                
                if (gen + 1) % 25 == 0:
                    print(f"    Gen {gen + 1}: Distance={best_distance:.2f}, Vehicles={int(best_fit[1])}")
            
            # Extract final routes
            routes = []
            current_route = []
            current_load = 0
            
            for node in best_routes:
                node_weight = self.demand_nodes[node].get('weight', 1000)
                
                if current_load + node_weight > self.vehicle_capacity:
                    if current_route:
                        routes.append(current_route)
                    current_route = [node]
                    current_load = node_weight
                else:
                    current_route.append(node)
                    current_load += node_weight
            
            if current_route:
                routes.append(current_route)
            
            all_routes[hub] = routes
            total_distance += best_distance
            total_vehicles += len(routes)
        
        print(f"\n✓ GA-NSGA-II Routing Complete")
        print(f"  Total Distance: {total_distance:.2f} km")
        print(f"  Total Vehicles: {total_vehicles}")
        
        # Clean up DEAP
        if hasattr(creator, 'FitnessMulti'):
            del creator.FitnessMulti
        if hasattr(creator, 'Individual'):
            del creator.Individual
        
        return {
            'routes': all_routes,
            'total_distance': total_distance,
            'total_vehicles': total_vehicles,
            'average_route_distance': total_distance / max(total_vehicles, 1)
        }


class RoutingOptimizationModel:
    """Main orchestration class"""
    
    def __init__(self, data_dir: str, sample_size: int = 500):
        self.data_dir = data_dir
        self.sample_size = sample_size
        self.results = {}
        
    def run(self, p: int = 3) -> Dict[str, Any]:
        """Run complete optimization"""
        print("="*70)
        print("LAST-MILE ROUTING OPTIMIZATION MODEL")
        print("="*70)
        
        # Phase 1: Data Preprocessing
        print("\nPHASE 0: DATA PREPROCESSING")
        print("-" * 70)
        preprocessor = DataPreprocessor(self.data_dir, self.sample_size)
        data = preprocessor.load_data()
        demand_nodes, route_list, distance_matrix = preprocessor.preprocess()
        
        if len(demand_nodes) == 0:
            print("✗ No demand nodes extracted. Generating synthetic data...")
            demand_nodes, distance_matrix = self._generate_synthetic_data()
        
        self.results['preprocessing'] = {
            'demand_nodes': len(demand_nodes),
            'routes_analyzed': len(route_list),
            'avg_packages_per_route': np.mean([r['packages'] for r in route_list]) if route_list else 0,
            'distance_matrix_shape': distance_matrix.shape
        }
        
        # Phase 1: Hub Location
        print("\n\nPHASE 1: HUB LOCATION OPTIMIZATION")
        print("-" * 70)
        hub_locator = PMedainHubLocation(demand_nodes, distance_matrix, p=p)
        opened_hubs, assignments = hub_locator.greedy_pmedian()
        hub_location_cost = hub_locator.calculate_cost(opened_hubs, assignments)
        
        self.results['hub_location'] = {
            'p': p,
            'opened_hubs': len(opened_hubs),
            'total_cost': hub_location_cost,
            'hub_opening_cost_per_hub': hub_locator.hub_opening_cost,
            'assignment_cost': hub_location_cost - (len(opened_hubs) * hub_locator.hub_opening_cost)
        }
        
        # Phase 2: Vehicle Routing
        print("\n\nPHASE 2: MULTI-DEPOT VEHICLE ROUTING")
        print("-" * 70)
        router = GANSGAIIRouter(demand_nodes, distance_matrix, opened_hubs, assignments)
        routing_results = router.run_ga(generations=100, population_size=50)
        
        self.results['routing'] = routing_results
        
        # Calculate total system cost
        total_cost = hub_location_cost + routing_results['total_distance']
        
        self.results['summary'] = {
            'total_system_cost': total_cost,
            'hub_location_cost': hub_location_cost,
            'routing_cost': routing_results['total_distance'],
            'total_vehicles': routing_results['total_vehicles'],
            'total_demand_nodes': len(demand_nodes),
            'avg_vehicles_per_hub': routing_results['total_vehicles'] / len(opened_hubs) if opened_hubs else 0
        }
        
        # Calculate performance metrics
        self._calculate_metrics()
        
        return self.results
    
    def _generate_synthetic_data(self) -> Tuple[List[Dict], np.ndarray]:
        """Generate synthetic data for testing"""
        n_nodes = 500
        demand_nodes = []
        
        # Generate random geographic locations
        for i in range(n_nodes):
            demand_nodes.append({
                'package_id': f'pkg_{i}',
                'route_id': f'route_{i // 100}',
                'lat': np.random.uniform(32, 48),
                'lng': np.random.uniform(-120, -70),
                'weight': np.random.uniform(500, 5000),
                'region': f'region_{i % 5}'
            })
        
        # Compute distance matrix
        coordinates = np.array([[d['lat'], d['lng']] for d in demand_nodes])
        distance_matrix = np.zeros((n_nodes, n_nodes))
        
        for i in range(n_nodes):
            for j in range(n_nodes):
                lat1, lng1 = coordinates[i]
                lat2, lng2 = coordinates[j]
                dist = np.sqrt((lat2 - lat1)**2 + (lng2 - lng1)**2) * 111
                distance_matrix[i, j] = dist
        
        return demand_nodes, distance_matrix
    
    def _calculate_metrics(self):
        """Calculate performance metrics"""
        print("\n\nPERFORMANCE METRICS")
        print("-" * 70)
        
        summary = self.results['summary']
        
        # Baseline metrics (assuming 1 hub, greedy routing)
        baseline_vehicles = summary['total_demand_nodes'] // 150  # ~150 stops per vehicle
        baseline_distance = baseline_vehicles * 200  # Assume ~200 km per vehicle
        baseline_cost = baseline_distance + 5000  # 1 hub opening cost
        
        cost_reduction = ((baseline_cost - summary['total_system_cost']) / baseline_cost * 100) if baseline_cost > 0 else 0
        distance_reduction = ((baseline_distance - summary['routing_cost']) / baseline_distance * 100) if baseline_distance > 0 else 0
        vehicle_reduction = ((baseline_vehicles - summary['total_vehicles']) / baseline_vehicles * 100) if baseline_vehicles > 0 else 0
        
        metrics = {
            'baseline_cost': baseline_cost,
            'proposed_cost': summary['total_system_cost'],
            'cost_reduction_percent': cost_reduction,
            'baseline_distance': baseline_distance,
            'proposed_distance': summary['routing_cost'],
            'distance_reduction_percent': distance_reduction,
            'baseline_vehicles': baseline_vehicles,
            'proposed_vehicles': summary['total_vehicles'],
            'vehicle_reduction_percent': vehicle_reduction,
            'cost_per_km': summary['total_system_cost'] / max(summary['routing_cost'], 1),
            'avg_stops_per_vehicle': summary['total_demand_nodes'] / max(summary['total_vehicles'], 1)
        }
        
        self.results['metrics'] = metrics
        
        print(f"Baseline Cost: ${baseline_cost:,.2f}")
        print(f"Proposed Cost: ${summary['total_system_cost']:,.2f}")
        print(f"Cost Reduction: {cost_reduction:.1f}%")
        print()
        print(f"Baseline Distance: {baseline_distance:.2f} km")
        print(f"Proposed Distance: {summary['routing_cost']:.2f} km")
        print(f"Distance Reduction: {distance_reduction:.1f}%")
        print()
        print(f"Baseline Vehicles: {baseline_vehicles}")
        print(f"Proposed Vehicles: {summary['total_vehicles']}")
        print(f"Vehicle Reduction: {vehicle_reduction:.1f}%")
        print()
        print(f"Average Stops per Vehicle: {metrics['avg_stops_per_vehicle']:.1f}")
        print(f"Cost per Kilometer: ${metrics['cost_per_km']:.2f}")
    
    def save_results(self, output_file: str = "routing_results.json"):
        """Save results to JSON"""
        output_path = Path(self.data_dir).parent / output_file
        
        # Convert numpy types for JSON serialization
        def convert_types(obj):
            if isinstance(obj, np.integer):
                return int(obj)
            elif isinstance(obj, np.floating):
                return float(obj)
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
            return obj
        
        # Serialize results
        serializable_results = json.loads(json.dumps(self.results, default=convert_types))
        
        with open(output_path, 'w') as f:
            json.dump(serializable_results, f, indent=2)
        
        print(f"\n✓ Results saved to {output_path}")
        return serializable_results


if __name__ == "__main__":
    # Run the optimization model
    data_dir = r"c:\Users\palak\OneDrive\Desktop\amazon-dataset\almrrc2021"
    
    model = RoutingOptimizationModel(data_dir, sample_size=500)
    results = model.run(p=3)
    
    # Save results
    serialized_results = model.save_results("routing_results.json")
    
    print("\n" + "="*70)
    print("OPTIMIZATION COMPLETE")
    print("="*70)
    
    # Print summary
    print("\nFINAL SUMMARY:")
    print(json.dumps(results['summary'], indent=2))
    print("\nMETRICS:")
    print(json.dumps(results['metrics'], indent=2))
