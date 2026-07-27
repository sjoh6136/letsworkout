package com.mattvena.powerlifting.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.mattvena.powerlifting.model.GymProfile;
import org.springframework.stereotype.Service;

import java.io.File;
import java.util.*;

@Service
public class GymService {

    private final Map<String, GymProfile> gyms = new LinkedHashMap<>();
    private String activeGymId = "gym_default";
    private final File dataFile = new File("gym_settings.json");
    private final ObjectMapper mapper = new ObjectMapper();

    public GymService() {
        loadData();
    }

    private synchronized void loadData() {
        if (dataFile.exists()) {
            try {
                Map<String, Object> root = mapper.readValue(dataFile, new TypeReference<Map<String, Object>>() {});
                if (root.containsKey("activeGymId")) {
                    this.activeGymId = (String) root.get("activeGymId");
                }
                if (root.containsKey("gyms")) {
                    List<Map<String, Object>> gymList = (List<Map<String, Object>>) root.get("gyms");
                    for (Map<String, Object> gMap : gymList) {
                        GymProfile profile = mapper.convertValue(gMap, GymProfile.class);
                        gyms.put(profile.getId(), profile);
                    }
                }
            } catch (Exception e) {
                System.err.println("Failed to load gym_settings.json: " + e.getMessage());
            }
        }

        if (gyms.isEmpty()) {
            GymProfile defaultGym = new GymProfile("gym_default", "우리동네 헬스장", 20.0,
                    Arrays.asList(20.0, 15.0, 10.0, 5.0, 2.5, 1.25), 2.0);
            gyms.put(defaultGym.getId(), defaultGym);
            activeGymId = defaultGym.getId();
            saveData();
        }
    }

    public synchronized void saveData() {
        try {
            Map<String, Object> root = new HashMap<>();
            root.put("activeGymId", activeGymId);
            root.put("gyms", new ArrayList<>(gyms.values()));
            mapper.writerWithDefaultPrettyPrinter().writeValue(dataFile, root);
        } catch (Exception e) {
            System.err.println("Failed to save gym_settings.json: " + e.getMessage());
        }
    }

    public synchronized List<GymProfile> getAllGyms() {
        return new ArrayList<>(gyms.values());
    }

    public synchronized GymProfile getActiveGym() {
        GymProfile gym = gyms.get(activeGymId);
        if (gym == null && !gyms.isEmpty()) {
            gym = gyms.values().iterator().next();
            activeGymId = gym.getId();
        }
        return gym;
    }

    public synchronized GymProfile getGymById(String id) {
        return gyms.get(id);
    }

    public synchronized GymProfile createGym(String name, double barbellWeight, List<Double> availablePlates, double dumbbellInterval) {
        String id = "gym_" + System.currentTimeMillis();
        GymProfile gym = new GymProfile(id, name, barbellWeight, availablePlates, dumbbellInterval);
        gyms.put(id, gym);
        activeGymId = id;
        saveData();
        return gym;
    }

    public synchronized GymProfile updateGym(String id, GymProfile newSettings) {
        GymProfile gym = gyms.get(id);
        if (gym != null) {
            if (newSettings.getName() != null && !newSettings.getName().trim().isEmpty()) {
                gym.setName(newSettings.getName().trim());
            }
            gym.setBarbellWeight(newSettings.getBarbellWeight());
            if (newSettings.getAvailablePlates() != null) {
                gym.setAvailablePlates(newSettings.getAvailablePlates());
            }
            gym.setDumbbellInterval(newSettings.getDumbbellInterval());
            saveData();
        }
        return gym;
    }

    public synchronized boolean selectActiveGym(String id) {
        if (gyms.containsKey(id)) {
            this.activeGymId = id;
            saveData();
            return true;
        }
        return false;
    }

    public synchronized boolean deleteGym(String id) {
        if (gyms.size() <= 1) {
            return false; // Cannot delete last remaining gym
        }
        if (gyms.containsKey(id)) {
            gyms.remove(id);
            if (activeGymId.equals(id)) {
                activeGymId = gyms.keySet().iterator().next();
            }
            saveData();
            return true;
        }
        return false;
    }

    public synchronized void resetMachineLearning(String gymId, String exerciseName) {
        GymProfile gym = gyms.get(gymId);
        if (gym != null) {
            if (exerciseName == null || exerciseName.trim().isEmpty()) {
                gym.getMachineProgressionMap().clear();
            } else {
                gym.getMachineProgressionMap().remove(exerciseName.trim());
            }
            saveData();
        }
    }

    // --- Free Weight Plate Solver ---
    public static class PlateSolverResult {
        private final double originalTarget;
        private final double adjustedWeight;
        private final boolean adjusted;

        public PlateSolverResult(double originalTarget, double adjustedWeight, boolean adjusted) {
            this.originalTarget = originalTarget;
            this.adjustedWeight = adjustedWeight;
            this.adjusted = adjusted;
        }

        public double getOriginalTarget() { return originalTarget; }
        public double getAdjustedWeight() { return adjustedWeight; }
        public boolean isAdjusted() { return adjusted; }
    }

    public PlateSolverResult resolveFreeWeight(String exerciseName, double targetWeight) {
        GymProfile profile = getActiveGym();
        if (profile == null) {
            return new PlateSolverResult(targetWeight, targetWeight, false);
        }

        String name = exerciseName.toLowerCase();
        if (name.contains("덤벨") || name.contains("dumbbell")) {
            double interval = profile.getDumbbellInterval() > 0 ? profile.getDumbbellInterval() : 2.0;
            double adjusted = Math.round(targetWeight / interval) * interval;
            return new PlateSolverResult(targetWeight, adjusted, adjusted != targetWeight);
        }

        // Barbell exercise plate combination check
        double bar = profile.getBarbellWeight();
        List<Double> plates = profile.getAvailablePlates();
        if (plates == null || plates.isEmpty()) {
            return new PlateSolverResult(targetWeight, targetWeight, false);
        }

        double neededPlates = targetWeight - bar;
        if (neededPlates <= 0) {
            return new PlateSolverResult(targetWeight, bar, bar != targetWeight);
        }

        double sideNeeded = neededPlates / 2.0;

        // Check formable side weights using plates (allowing duplicates of available plate denominations)
        double closestSide = findClosestFormableSideWeight(sideNeeded, plates);
        double adjustedTotal = bar + (closestSide * 2.0);

        return new PlateSolverResult(targetWeight, adjustedTotal, adjustedTotal != targetWeight);
    }

    private double findClosestFormableSideWeight(double targetSide, List<Double> plateDenoms) {
        // Sort plate denominations descending
        List<Double> denoms = new ArrayList<>(plateDenoms);
        denoms.sort(Collections.reverseOrder());

        // Find smallest denomination for step granularity
        double minDenom = denoms.get(denoms.size() - 1);
        if (minDenom <= 0) minDenom = 1.25;

        // Check up to targetSide + 15kg in increments of minDenom
        double bestSide = targetSide;
        double minDiff = Double.MAX_VALUE;

        for (double testSide = targetSide; testSide <= targetSide + 20.0; testSide += minDenom) {
            if (canFormSide(testSide, denoms)) {
                return testSide;
            }
        }
        return Math.ceil(targetSide / minDenom) * minDenom;
    }

    private boolean canFormSide(double amount, List<Double> denoms) {
        if (Math.abs(amount) < 0.001) return true;
        if (amount < 0) return false;
        for (double d : denoms) {
            if (d <= amount + 0.001) {
                if (canFormSide(amount - d, denoms)) return true;
            }
        }
        return false;
    }

    // --- Machine Auto-Learning ---
    public synchronized void learnMachineWeight(String exerciseName, String weightStr) {
        GymProfile gym = getActiveGym();
        if (gym == null || exerciseName == null || weightStr == null) return;

        String exKey = exerciseName.trim();
        String wVal = weightStr.trim();
        if (wVal.isEmpty()) return;

        Map<String, List<String>> map = gym.getMachineProgressionMap();
        List<String> list = map.computeIfAbsent(exKey, k -> new ArrayList<>());

        if (!list.contains(wVal)) {
            list.add(wVal);
            // Try to sort numerically if all elements can be parsed as numbers
            sortMachineSequence(list);
            saveData();
        }
    }

    public synchronized String getNextMachineRecommendation(String exerciseName, String currentWeightStr) {
        GymProfile gym = getActiveGym();
        if (gym == null || exerciseName == null) return null;

        List<String> list = gym.getMachineProgressionMap().get(exerciseName.trim());
        if (list != null && !list.isEmpty() && currentWeightStr != null) {
            String cur = currentWeightStr.trim();
            int idx = list.indexOf(cur);
            if (idx >= 0 && idx + 1 < list.size()) {
                return list.get(idx + 1);
            }
        }
        return null;
    }

    private void sortMachineSequence(List<String> list) {
        try {
            list.sort((a, b) -> {
                double numA = parseNum(a);
                double numB = parseNum(b);
                return Double.compare(numA, numB);
            });
        } catch (Exception e) {
            // Keep insertion order if non-numeric
        }
    }

    private double parseNum(String s) {
        String cleaned = s.replaceAll("[^0-9.]", "").trim();
        return cleaned.isEmpty() ? 0.0 : Double.parseDouble(cleaned);
    }
}
