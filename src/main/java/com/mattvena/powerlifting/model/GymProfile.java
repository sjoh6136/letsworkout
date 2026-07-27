package com.mattvena.powerlifting.model;

import java.util.*;

public class GymProfile {
    private String id;
    private String name;
    private double barbellWeight;
    private List<Double> availablePlates;
    private double dumbbellInterval;
    private Map<String, List<String>> machineProgressionMap;

    public GymProfile() {
        this.id = "gym_default";
        this.name = "우리동네 헬스장";
        this.barbellWeight = 20.0;
        this.availablePlates = new ArrayList<>(Arrays.asList(20.0, 15.0, 10.0, 5.0, 2.5, 1.25));
        this.dumbbellInterval = 2.0;
        this.machineProgressionMap = new HashMap<>();
    }

    public GymProfile(String id, String name, double barbellWeight, List<Double> availablePlates, double dumbbellInterval) {
        this.id = id;
        this.name = name;
        this.barbellWeight = barbellWeight;
        this.availablePlates = availablePlates != null ? availablePlates : new ArrayList<>(Arrays.asList(20.0, 15.0, 10.0, 5.0, 2.5, 1.25));
        this.dumbbellInterval = dumbbellInterval;
        this.machineProgressionMap = new HashMap<>();
    }

    public String getId() {
        return id;
    }

    public void setId(String id) {
        this.id = id;
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public double getBarbellWeight() {
        return barbellWeight;
    }

    public void setBarbellWeight(double barbellWeight) {
        this.barbellWeight = barbellWeight;
    }

    public List<Double> getAvailablePlates() {
        return availablePlates;
    }

    public void setAvailablePlates(List<Double> availablePlates) {
        this.availablePlates = availablePlates;
    }

    public double getDumbbellInterval() {
        return dumbbellInterval;
    }

    public void setDumbbellInterval(double dumbbellInterval) {
        this.dumbbellInterval = dumbbellInterval;
    }

    public Map<String, List<String>> getMachineProgressionMap() {
        if (machineProgressionMap == null) {
            machineProgressionMap = new HashMap<>();
        }
        return machineProgressionMap;
    }

    public void setMachineProgressionMap(Map<String, List<String>> machineProgressionMap) {
        this.machineProgressionMap = machineProgressionMap;
    }
}
