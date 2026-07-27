package com.mattvena.powerlifting.controller;

import com.mattvena.powerlifting.model.*;
import com.mattvena.powerlifting.service.AutoregulationService;
import com.mattvena.powerlifting.service.GoogleSheetsService;
import com.mattvena.powerlifting.service.GymService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.core.io.Resource;
import org.springframework.core.io.ResourceLoader;

import java.util.*;

@RestController
@RequestMapping("/api/workout")
@CrossOrigin(origins = "*")
public class WorkoutController {

    @Autowired
    private GoogleSheetsService googleSheetsService;

    @Autowired
    private AutoregulationService autoregulationService;

    @Autowired
    private ResourceLoader resourceLoader;

    @Autowired
    private GymService gymService;

    private final Set<String> largeMuscles = new HashSet<>();
    private final Set<String> smallMuscles = new HashSet<>();
    private boolean definitionsLoaded = false;

    private synchronized void loadExerciseDefinitions() {
        if (definitionsLoaded) return;
        try {
            Resource resource = resourceLoader.getResource("classpath:exercise_definitions.json");
            ObjectMapper mapper = new ObjectMapper();
            Map<String, List<String>> map = mapper.readValue(resource.getInputStream(), new TypeReference<Map<String, List<String>>>() {});
            if (map.containsKey("large_muscles")) {
                largeMuscles.addAll(map.get("large_muscles"));
            }
            if (map.containsKey("small_muscles")) {
                smallMuscles.addAll(map.get("small_muscles"));
            }
            definitionsLoaded = true;
        } catch (Exception e) {
            System.err.println("Failed to load exercise definitions: " + e.getMessage());
        }
    }

    private double getIncrement(String exerciseName) {
        loadExerciseDefinitions();
        String name = exerciseName.trim();
        if (largeMuscles.contains(name)) {
            return 5.0;
        }
        if (smallMuscles.contains(name)) {
            return 2.5;
        }
        // Fallback checks
        String lower = name.toLowerCase();
        if (lower.contains("스쿼트") || lower.contains("squat") ||
            lower.contains("데드리프트") || lower.contains("deadlift") ||
            lower.contains("벤치프레스") || lower.contains("bench") ||
            lower.contains("레그 프레스") || lower.contains("레그프레스") || lower.contains("leg press")) {
            return 5.0;
        }
        return 2.5;
    }

    @GetMapping("/settings")
    public Map<String, Object> getSettings() {
        OneRmSetting oneRms = googleSheetsService.getOneRm();
        Map<String, Object> response = new HashMap<>();
        response.put("oneRms", oneRms);
        response.put("sheetsConnected", !googleSheetsService.isFallback());
        return response;
    }

    @PostMapping("/settings")
    public OneRmSetting updateSettings(@RequestBody OneRmSetting newSettings) {
        googleSheetsService.updateOneRm(newSettings);
        return googleSheetsService.getOneRm();
    }

    @GetMapping("/gyms")
    public Map<String, Object> getGyms() {
        Map<String, Object> res = new HashMap<>();
        res.put("activeGymId", gymService.getActiveGym() != null ? gymService.getActiveGym().getId() : null);
        res.put("gyms", gymService.getAllGyms());
        return res;
    }

    @PostMapping("/gyms")
    public GymProfile createGym(@RequestBody GymProfile newGym) {
        return gymService.createGym(newGym.getName(), newGym.getBarbellWeight(), newGym.getAvailablePlates(), newGym.getDumbbellInterval());
    }

    @PutMapping("/gyms/{id}")
    public GymProfile updateGym(@PathVariable String id, @RequestBody GymProfile newSettings) {
        return gymService.updateGym(id, newSettings);
    }

    @PostMapping("/gyms/select/{id}")
    public Map<String, Object> selectGym(@PathVariable String id) {
        boolean success = gymService.selectActiveGym(id);
        Map<String, Object> res = new HashMap<>();
        res.put("success", success);
        res.put("activeGym", gymService.getActiveGym());
        return res;
    }

    @DeleteMapping("/gyms/{id}")
    public Map<String, Object> deleteGym(@PathVariable String id) {
        boolean success = gymService.deleteGym(id);
        Map<String, Object> res = new HashMap<>();
        res.put("success", success);
        res.put("gyms", gymService.getAllGyms());
        return res;
    }

    @PostMapping("/gyms/{id}/reset-machine")
    public Map<String, Object> resetMachine(@PathVariable String id, @RequestParam(required = false) String exercise) {
        gymService.resetMachineLearning(id, exercise);
        Map<String, Object> res = new HashMap<>();
        res.put("success", true);
        return res;
    }

    @PostMapping("/finish")
    public WorkoutFeedbackResponse finishWorkout(@RequestBody FinishWorkoutRequest request) {
        OneRmSetting current1Rms = googleSheetsService.getOneRm();
        
        // Evaluate failure conditions & update 1RMs accordingly
        AutoregulationService.EvaluationResult eval = autoregulationService.evaluateWorkout(request.getLogs(), current1Rms);
        
        if (eval.isUpdated()) {
            googleSheetsService.updateOneRm(current1Rms);
        }

        // Add date, split, week, and day to logs
        String todayStr = new java.text.SimpleDateFormat("yyyy-MM-dd").format(new Date());
        for (WorkoutLog log : request.getLogs()) {
            if (log.getDate() == null || log.getDate().trim().isEmpty()) {
                log.setDate(todayStr);
            }
            log.setSplit(request.getSplit());
            log.setWeek(request.getWeek());
            log.setDay(request.getDay());
        }

        // Learn machine weights if applicable
        for (WorkoutLog log : request.getLogs()) {
            if (log.getWeight() > 0) {
                gymService.learnMachineWeight(log.getExercise(), String.valueOf(log.getWeight()));
            }
        }

        // Save to spreadsheet (or in-memory)
        googleSheetsService.appendWorkoutLogs(request.getLogs());

        // --- COMPUTE STATISTICS FOR FEEDBACK ---
        double totalVolume = 0;
        int completedSets = 0;
        int totalSets = request.getLogs().size();
        for (WorkoutLog log : request.getLogs()) {
            if ("SUCCESS".equalsIgnoreCase(log.getStatus())) {
                totalVolume += log.getWeight() * log.getReps();
                completedSets++;
            }
        }

        // Generate Progressive Overload Progress Report (on-the-fly)
        List<String> progressReport = new ArrayList<>();
        Map<String, List<WorkoutLog>> logsByExercise = new HashMap<>();
        for (WorkoutLog log : request.getLogs()) {
            logsByExercise.computeIfAbsent(log.getExercise(), k -> new ArrayList<>()).add(log);
        }

        // Get repsRange mapping from current split
        Map<String, String> rangeMap = new HashMap<>();
        Map<String, Boolean> coreMap = new HashMap<>();
        Map<String, Double> rpeTargetMap = new HashMap<>();
        Map<String, Integer> targetRepsMap = new HashMap<>();

        Map<String, List<Map<String, Object>>> tempRoutineMap = getStaticRoutines();
        List<Map<String, Object>> activeSplitDays = tempRoutineMap.get(String.valueOf(request.getSplit()));
        if (activeSplitDays != null) {
            for (Map<String, Object> day : activeSplitDays) {
                List<Map<String, Object>> exList = (List<Map<String, Object>>) day.get("exercises");
                if (exList != null) {
                    for (Map<String, Object> ex : exList) {
                        String name = (String) ex.get("name");
                        rangeMap.put(name, (String) ex.get("repsRange"));
                        coreMap.put(name, (boolean) ex.get("coreLift"));
                        rpeTargetMap.put(name, (double) ex.get("rpeTarget"));
                        targetRepsMap.put(name, (int) ex.get("targetReps"));
                    }
                }
            }
        }

        for (String exName : logsByExercise.keySet()) {
            List<WorkoutLog> exLogs = logsByExercise.get(exName);
            String repsRange = rangeMap.getOrDefault(exName, "8~12");
            boolean coreLift = coreMap.getOrDefault(exName, false);
            double rpeTarget = rpeTargetMap.getOrDefault(exName, 8.5);
            int targetReps = targetRepsMap.getOrDefault(exName, 8);

            int minReps = 8;
            int maxReps = 12;
            if (repsRange != null && (repsRange.contains("~") || repsRange.contains("-"))) {
                String[] parts = repsRange.split("[~-]");
                try {
                    minReps = Integer.parseInt(parts[0].trim());
                    maxReps = Integer.parseInt(parts[1].trim());
                } catch (Exception e) {}
            } else if (repsRange != null) {
                try {
                    minReps = Integer.parseInt(repsRange.trim());
                    maxReps = minReps;
                } catch (Exception e) {}
            }

            boolean allSuccess = true;
            double prevWeight = 0;
            int prevTargetReps = targetReps;
            for (WorkoutLog log : exLogs) {
                prevWeight = log.getWeight();
                prevTargetReps = log.getTargetReps();
                
                // Progress criteria: status is SUCCESS + completed reps >= target reps + actual RPE <= target RPE!
                boolean setSucceeded = "SUCCESS".equalsIgnoreCase(log.getStatus()) 
                                    && log.getReps() >= log.getTargetReps() 
                                    && log.getRpe() <= rpeTarget;
                if (!setSucceeded) {
                    allSuccess = false;
                }
            }

            if (allSuccess) {
                if (prevTargetReps < maxReps) {
                    progressReport.add("💪 " + exName + ": 횟수 증가 (다음 " + (prevTargetReps + 1) + "회)");
                } else {
                    double increment = getIncrement(exName);
                    progressReport.add("🚀 " + exName + ": 무게 증량 (다음 +" + increment + "kg, " + minReps + "회)");
                }
            } else {
                progressReport.add("❄️ " + exName + ": 유지 (실패/강도초과)");
            }
        }

        // Calculate Weekly Target Muscle Sets Volume
        List<WorkoutLog> updatedLogs = googleSheetsService.getWorkoutLogs();
        Map<String, Integer> weeklyMuscleSets = new LinkedHashMap<>();
        weeklyMuscleSets.put("가슴", 0);
        weeklyMuscleSets.put("등", 0);
        weeklyMuscleSets.put("하체", 0);
        weeklyMuscleSets.put("어깨", 0);
        weeklyMuscleSets.put("팔", 0);

        if (updatedLogs != null) {
            for (WorkoutLog log : updatedLogs) {
                if (log.getSplit() == request.getSplit() && log.getWeek() == request.getWeek()) {
                    if ("SUCCESS".equalsIgnoreCase(log.getStatus())) {
                        String muscle = getTargetMuscle(log.getExercise());
                        if (weeklyMuscleSets.containsKey(muscle)) {
                            weeklyMuscleSets.put(muscle, weeklyMuscleSets.get(muscle) + 1);
                        }
                    }
                }
            }
        }

        // Calculate Deload Alert
        String deloadAlert = null;
        double totalRpe = 0;
        int rpeCount = 0;
        boolean hasFailure = false;
        for (WorkoutLog log : request.getLogs()) {
            if (log.getReps() < log.getTargetReps()) {
                hasFailure = true;
            }
            if (log.getRpe() > 0) {
                totalRpe += log.getRpe();
                rpeCount++;
            }
        }
        double avgRpe = rpeCount > 0 ? (totalRpe / rpeCount) : 0.0;

        if (hasFailure && avgRpe >= 9.0) {
            deloadAlert = "session";
        }

        // If 2 or more days are marked fatigued
        int fatiguedDaysCount = 0;
        if (current1Rms.isFatigueDay1()) fatiguedDaysCount++;
        if (current1Rms.isFatigueDay2()) fatiguedDaysCount++;
        if (current1Rms.isFatigueDay3()) fatiguedDaysCount++;
        if (current1Rms.isFatigueDay4()) fatiguedDaysCount++;
        if (current1Rms.isFatigueDay5()) fatiguedDaysCount++;

        if (fatiguedDaysCount >= 2) {
            deloadAlert = "weekly";
        }

        return new WorkoutFeedbackResponse(
                eval.getStatus(),
                eval.getFeedback(),
                !googleSheetsService.isFallback(),
                totalVolume,
                completedSets,
                totalSets,
                progressReport,
                weeklyMuscleSets,
                deloadAlert
        );
    }

    @GetMapping("/logs")
    public List<WorkoutLog> getLogs() {
        return googleSheetsService.getWorkoutLogs();
    }

    @GetMapping("/status")
    public Map<String, Object> getStatus() {
        List<WorkoutLog> logs = googleSheetsService.getWorkoutLogs();
        OneRmSetting setting = googleSheetsService.getOneRm();
        int activeSplit = setting.getActiveSplit();
        
        Map<String, Object> response = new HashMap<>();
        response.put("sheetsConnected", !googleSheetsService.isFallback());
        
        String lastCompleted = null;
        String nextRecommended = "Day 1"; // Default
        
        if (logs != null && !logs.isEmpty()) {
            for (int i = logs.size() - 1; i >= 0; i--) {
                WorkoutLog log = logs.get(i);
                if (log.getSplit() == activeSplit) {
                    String lastDay = log.getDay();
                    int lastDayNum = 1;
                    if (lastDay != null) {
                        try {
                            lastDayNum = Integer.parseInt(lastDay.replaceAll("[^0-9]", "").trim());
                        } catch (Exception ex) {}
                    }
                    
                    lastCompleted = "Day " + lastDayNum;
                    int nextNum = lastDayNum + 1;
                    if (nextNum > activeSplit) {
                        nextNum = 1;
                    }
                    nextRecommended = "Day " + nextNum;
                    break;
                }
            }
        }
        
        response.put("lastCompletedDay", lastCompleted);
        response.put("nextRecommendedDay", nextRecommended);
        return response;
    }

    @GetMapping("/routine")
    public Map<String, List<Map<String, Object>>> getRoutine() {
        Map<String, List<Map<String, Object>>> routineMap = getStaticRoutines();

        // Apply Double Progression dynamically
        List<WorkoutLog> allLogs = googleSheetsService.getWorkoutLogs();
        OneRmSetting oneRms = googleSheetsService.getOneRm();

        for (String splitKey : routineMap.keySet()) {
            int splitNum = Integer.parseInt(splitKey);
            for (Map<String, Object> day : routineMap.get(splitKey)) {
                List<Map<String, Object>> exercises = (List<Map<String, Object>>) day.get("exercises");
                for (Map<String, Object> ex : exercises) {
                    applyDoubleProgression(ex, allLogs, oneRms, splitNum);
                }
            }
        }

        return routineMap;
    }

    private Map<String, List<Map<String, Object>>> getStaticRoutines() {
        Map<String, List<Map<String, Object>>> routineMap = new HashMap<>();
        
        // === 2-Split ===
        List<Map<String, Object>> split2 = new ArrayList<>();
        split2.add(createDay("Day 1", "Day 1 - 상체 (Upper Body) | 가슴·등·어깨·팔", Arrays.asList(
                createExercise("플랫 바벨 벤치프레스", 3, 6, "6~8", 8.0, true, "bench", 0.75, 0.0),
                createExercise("바벨 로우 (Bent-over Row)", 3, 6, "6~8", 8.0, false, null, 0.0, 50.0),
                createExercise("인클라인 덤벨 프레스", 3, 8, "8~10", 8.0, false, null, 0.0, 25.0),
                createExercise("랫 풀 다운", 3, 8, "8~10", 9.0, false, null, 0.0, 45.0),
                createExercise("사이드 레터럴 레이즈 (덤벨)", 3, 10, "10~12", 9.0, false, null, 0.0, 8.0),
                createExercise("이두 바벨 컬", 3, 10, "10~12", 9.0, false, null, 0.0, 30.0)
        )));
        split2.add(createDay("Day 2", "Day 2 - 하체 (Lower Body) | 대퇴사두·햄스트링", Arrays.asList(
                createExercise("백 스쿼트 (바벨)", 3, 6, "6~8", 8.0, true, "squat", 0.75, 0.0),
                createExercise("덤벨 루마니안 데드리프트 (RDL)", 3, 8, "8~10", 8.0, true, "deadlift", 0.60, 0.0),
                createExercise("레그 프레스 (머신)", 3, 8, "8~10", 9.0, false, null, 0.0, 120.0),
                createExercise("시티드 레그 컬", 3, 10, "10~12", 9.0, false, null, 0.0, 35.0),
                createExercise("스탠딩 카프 레이즈", 3, 12, "12~15", 9.0, false, null, 0.0, 40.0)
        )));
        routineMap.put("2", split2);

        // === 3-Split ===
        List<Map<String, Object>> split3 = new ArrayList<>();
        split3.add(createDay("Day 1", "Day 1 - 밀기 (Push) | 가슴·어깨·삼두", Arrays.asList(
                createExercise("플랫 바벨 벤치프레스", 3, 6, "6~8", 8.0, true, "bench", 0.75, 0.0),
                createExercise("오버헤드 프레스 (OHP - 바벨)", 3, 6, "6~8", 8.0, true, "ohp", 0.75, 0.0),
                createExercise("인클라인 덤벨 프레스", 3, 8, "8~10", 9.0, false, null, 0.0, 25.0),
                createExercise("사이드 레터럴 레이즈 (덤벨)", 4, 10, "10~12", 9.0, false, null, 0.0, 8.0),
                createExercise("라잉 트라이셉스 익스텐션", 3, 10, "10~12", 9.0, false, null, 0.0, 25.0)
        )));
        split3.add(createDay("Day 2", "Day 2 - 당기기 (Pull) | 등·이두", Arrays.asList(
                createExercise("바벨 로우 (Bent-over Row)", 3, 6, "6~8", 8.0, false, null, 0.0, 50.0),
                createExercise("풀업 또는 랫 풀 다운", 3, 8, "8~10", 9.0, false, null, 0.0, 45.0),
                createExercise("원암 덤벨 로우", 3, 8, "8~10", 9.0, false, null, 0.0, 20.0),
                createExercise("페이스 풀 (케이블)", 3, 10, "10~12", 9.0, false, null, 0.0, 15.0),
                createExercise("이두 바벨 컬", 3, 10, "10~12", 9.0, false, null, 0.0, 30.0)
        )));
        split3.add(createDay("Day 3", "Day 3 - 하체 (Legs) | 대퇴사두·햄스트링", Arrays.asList(
                createExercise("백 스쿼트 (바벨)", 3, 6, "6~8", 8.0, true, "squat", 0.75, 0.0),
                createExercise("덤벨 루마니안 데드리프트 (RDL)", 3, 8, "8~10", 8.0, true, "deadlift", 0.60, 0.0),
                createExercise("레그 익스텐션", 3, 10, "10~12", 9.0, false, null, 0.0, 40.0),
                createExercise("시티드 레그 컬", 3, 10, "10~12", 9.0, false, null, 0.0, 35.0),
                createExercise("행잉 레그 레이즈", 3, 12, "12~15", 9.0, false, null, 0.0, 0.0)
        )));
        routineMap.put("3", split3);

        // === 4-Split ===
        List<Map<String, Object>> split4 = new ArrayList<>();
        split4.add(createDay("Day 1", "Day 1 - 가슴·이두 (Chest & Biceps) | 가슴·이두", Arrays.asList(
                createExercise("플랫 바벨 벤치프레스", 3, 6, "6~8", 8.0, true, "bench", 0.75, 0.0),
                createExercise("바벨 펜들레이 로우", 3, 6, "6~8", 8.0, false, null, 0.0, 50.0),
                createExercise("인클라인 덤벨 프레스", 3, 8, "8~10", 9.0, false, null, 0.0, 25.0),
                createExercise("풀업", 3, 8, "8~10", 8.0, false, null, 0.0, 0.0),
                createExercise("이두 바벨 컬", 3, 10, "10~12", 9.0, false, null, 0.0, 30.0)
        )));
        split4.add(createDay("Day 2", "Day 2 - 하체 (Legs) | 대퇴사두·햄스트링", Arrays.asList(
                createExercise("백 스쿼트 (바벨)", 3, 6, "6~8", 8.0, true, "squat", 0.75, 0.0),
                createExercise("덤벨 루마니안 데드리프트 (RDL)", 3, 8, "8~10", 8.0, true, "deadlift", 0.60, 0.0),
                createExercise("레그 프레스 (머신)", 3, 8, "8~10", 9.0, false, null, 0.0, 120.0),
                createExercise("라잉 레그 컬", 3, 10, "10~12", 9.0, false, null, 0.0, 35.0),
                createExercise("스탠딩 카프 레이즈", 3, 12, "12~15", 9.0, false, null, 0.0, 40.0)
        )));
        split4.add(createDay("Day 3", "Day 3 - 어깨·삼두 (Shoulders & Triceps) | 어깨·삼두", Arrays.asList(
                createExercise("오버헤드 프레스 (OHP - 바벨)", 3, 6, "6~8", 8.0, true, "ohp", 0.75, 0.0),
                createExercise("랫 풀 다운", 3, 8, "8~10", 9.0, false, null, 0.0, 45.0),
                createExercise("시티드 케이블 로우", 3, 8, "8~10", 9.0, false, null, 0.0, 40.0),
                createExercise("딥스 (Dips)", 3, 8, "8~10", 8.0, false, null, 0.0, 0.0),
                createExercise("사이드 레터럴 레이즈 (덤벨)", 4, 10, "10~12", 9.0, false, null, 0.0, 8.0)
        )));
        split4.add(createDay("Day 4", "Day 4 - 등 (Back) | 등", Arrays.asList(
                createExercise("컨벤셔널 데드리프트", 3, 5, "5", 8.0, true, "deadlift", 0.75, 0.0),
                createExercise("불가리안 스플릿 스쿼트 (BSS)", 3, 8, "8~10", 9.0, false, null, 0.0, 15.0),
                createExercise("레그 익스텐션", 3, 10, "10~12", 9.0, false, null, 0.0, 40.0),
                createExercise("시티드 레그 컬", 3, 10, "10~12", 9.0, false, null, 0.0, 35.0),
                createExercise("행잉 레그 레이즈", 3, 12, "12~15", 9.0, false, null, 0.0, 0.0)
        )));
        routineMap.put("4", split4);

        // === 5-Split ===
        List<Map<String, Object>> split5 = new ArrayList<>();
        split5.add(createDay("Day 1", "Day 1 - 상체 (Upper) | 가슴·등·어깨·팔", Arrays.asList(
                createExercise("인클라인 덤벨 프레스", 3, 8, "8~10", 8.0, false, null, 0.0, 25.0),
                createExercise("랫 풀 다운", 3, 8, "8~10", 8.0, false, null, 0.0, 45.0),
                createExercise("오버헤드 프레스 (OHP - 바벨)", 3, 8, "8~10", 8.0, true, "ohp", 0.75, 0.0),
                createExercise("시티드 케이블 로우", 3, 10, "10~12", 9.0, false, null, 0.0, 40.0),
                createExercise("사이드 레터럴 레이즈 (덤벨)", 3, 12, "12~15", 9.0, false, null, 0.0, 8.0)
        )));
        split5.add(createDay("Day 2", "Day 2 - 하체 (Lower) | 대퇴사두·햄스트링", Arrays.asList(
                createExercise("백 스쿼트 (바벨)", 3, 6, "6~8", 8.0, true, "squat", 0.75, 0.0),
                createExercise("덤벨 루마니안 데드리프트 (RDL)", 3, 8, "8~10", 8.0, true, "deadlift", 0.60, 0.0),
                createExercise("레그 익스텐션", 3, 12, "12~15", 9.0, false, null, 0.0, 40.0),
                createExercise("시티드 레그 컬", 3, 10, "10~12", 9.0, false, null, 0.0, 35.0),
                createExercise("스탠딩 카프 레이즈", 3, 12, "12~15", 9.0, false, null, 0.0, 40.0)
        )));
        split5.add(createDay("Day 3", "Day 3 - 밀기 (Push) | 가슴·어깨·삼두", Arrays.asList(
                createExercise("플랫 바벨 벤치프레스", 3, 8, "8~10", 8.0, true, "bench", 0.75, 0.0),
                createExercise("스탠딩 덤벨 숄더 프레스", 3, 10, "10~12", 9.0, false, null, 0.0, 18.0),
                createExercise("디클라인 케이블 플라이", 3, 12, "12~15", 9.0, false, null, 0.0, 15.0),
                createExercise("케이블 트라이셉스 푸시다운", 3, 12, "12~15", 9.0, false, null, 0.0, 20.0),
                createExercise("사이드 레터럴 레이즈 (덤벨)", 3, 12, "12~15", 9.0, false, null, 0.0, 8.0)
        )));
        split5.add(createDay("Day 4", "Day 4 - 당기기 (Pull) | 등·이두", Arrays.asList(
                createExercise("원암 덤벨 로우", 3, 8, "8~10", 9.0, false, null, 0.0, 20.0),
                createExercise("랫 풀 다운 (와이드 그립)", 3, 10, "10~12", 9.0, false, null, 0.0, 45.0),
                createExercise("페이스 풀 (케이블)", 3, 12, "12~15", 9.0, false, null, 0.0, 15.0),
                createExercise("인클라인 덤벨 컬", 3, 10, "10~12", 9.0, false, null, 0.0, 12.0),
                createExercise("해머 컬", 3, 10, "10~12", 9.0, false, null, 0.0, 12.0)
        )));
        split5.add(createDay("Day 5", "Day 5 - 다리 (Legs) | 대퇴사두·햄스트링", Arrays.asList(
                createExercise("레그 프레스 (머신)", 3, 10, "10~12", 8.0, false, null, 0.0, 120.0),
                createExercise("불가리안 스플릿 스쿼트 (BSS)", 3, 8, "8~10", 9.0, false, null, 0.0, 15.0),
                createExercise("라잉 레그 컬", 3, 12, "12~15", 9.0, false, null, 0.0, 35.0),
                createExercise("시티드 카프 레이즈", 3, 12, "12~15", 9.0, false, null, 0.0, 30.0),
                createExercise("행잉 레그 레이즈", 3, 15, "15", 9.0, false, null, 0.0, 0.0)
        )));
        routineMap.put("5", split5);

        return routineMap;
    }

    private void applyDoubleProgression(Map<String, Object> ex, List<WorkoutLog> allLogs, OneRmSetting oneRms, int activeSplit) {
        String name = (String) ex.get("name");
        String repsRange = (String) ex.get("repsRange");
        int sets = (int) ex.get("sets");
        boolean coreLift = (boolean) ex.get("coreLift");
        String coreLiftType = (String) ex.get("coreLiftType");
        double intensity = (double) ex.get("intensity");
        double defaultWeight = (double) ex.get("defaultWeight");
        double rpeTarget = (double) ex.get("rpeTarget");

        int minReps = 8;
        int maxReps = 12;
        if (repsRange != null && (repsRange.contains("~") || repsRange.contains("-"))) {
            String[] parts = repsRange.split("[~-]");
            try {
                minReps = Integer.parseInt(parts[0].trim());
                maxReps = Integer.parseInt(parts[1].trim());
            } catch (Exception e) {}
        } else if (repsRange != null) {
            try {
                minReps = Integer.parseInt(repsRange.trim());
                maxReps = minReps;
            } catch (Exception e) {}
        }

        List<WorkoutLog> exerciseLogs = new ArrayList<>();
        if (allLogs != null) {
            String maxDate = "";
            for (WorkoutLog log : allLogs) {
                if (log.getSplit() == activeSplit && name.equals(log.getExercise())) {
                    String d = log.getDate();
                    if (d != null && d.compareTo(maxDate) > 0) {
                        maxDate = d;
                    }
                }
            }
            if (!maxDate.isEmpty()) {
                for (WorkoutLog log : allLogs) {
                    if (log.getSplit() == activeSplit && name.equals(log.getExercise()) && maxDate.equals(log.getDate())) {
                        exerciseLogs.add(log);
                    }
                }
            }
        }

        double targetWeight;
        int targetRepsVal;

        if (exerciseLogs.isEmpty()) {
            if (coreLift && coreLiftType != null && !coreLiftType.isEmpty()) {
                double baseOneRm = getOneRmVal(oneRms, coreLiftType);
                double rawWeight = baseOneRm * intensity;
                targetWeight = Math.round(rawWeight / 2.5) * 2.5;
            } else {
                targetWeight = defaultWeight;
            }
            targetRepsVal = minReps;
        } else {
            boolean allSuccess = true;
            double prevWeight = exerciseLogs.get(exerciseLogs.size() - 1).getWeight();
            int prevTargetReps = exerciseLogs.get(exerciseLogs.size() - 1).getTargetReps();

            for (WorkoutLog log : exerciseLogs) {
                boolean setSucceeded = "SUCCESS".equalsIgnoreCase(log.getStatus()) 
                                    && log.getReps() >= log.getTargetReps() 
                                    && log.getRpe() <= rpeTarget;
                if (!setSucceeded) {
                    allSuccess = false;
                }
            }

            if (allSuccess) {
                if (prevTargetReps < maxReps) {
                    targetRepsVal = prevTargetReps + 1;
                    targetWeight = prevWeight;
                } else {
                    targetRepsVal = minReps;
                    double increment = getIncrement(name);
                    targetWeight = prevWeight + increment;
                }
            } else {
                // allow a smaller rep progression when the previous session was close to target
                boolean nearSuccess = true;
                for (WorkoutLog log : exerciseLogs) {
                    if (log.getReps() < log.getTargetReps() - 2) {
                        nearSuccess = false;
                        break;
                    }
                }
                if (nearSuccess && prevTargetReps < maxReps) {
                    targetRepsVal = prevTargetReps + 1;
                    targetWeight = prevWeight;
                } else {
                    targetRepsVal = prevTargetReps;
                    targetWeight = prevWeight;
                }
            }
        }

        // Inject previousLog details and per-set previous records for UI display
        if (!exerciseLogs.isEmpty()) {
            Map<String, Object> prevMap = new HashMap<>();
            prevMap.put("date", exerciseLogs.get(0).getDate());
            prevMap.put("weight", exerciseLogs.get(exerciseLogs.size() - 1).getWeight());
            prevMap.put("reps", exerciseLogs.get(exerciseLogs.size() - 1).getReps());
            prevMap.put("sets", exerciseLogs.size());
            prevMap.put("rpe", exerciseLogs.get(exerciseLogs.size() - 1).getRpe());
            ex.put("previousLog", prevMap);

            Map<Integer, WorkoutLog> prevSetMap = new HashMap<>();
            for (WorkoutLog log : exerciseLogs) {
                prevSetMap.put(log.getSetNo(), log);
            }
            int setsCount = ex.containsKey("sets") ? (int) ex.get("sets") : 0;
            List<Map<String, Object>> previousSets = new ArrayList<>();
            for (int i = 1; i <= setsCount; i++) {
                WorkoutLog logEntry = prevSetMap.get(i);
                if (logEntry != null) {
                    Map<String, Object> setMapObj = new HashMap<>();
                    setMapObj.put("weight", logEntry.getWeight());
                    setMapObj.put("reps", logEntry.getReps());
                    previousSets.add(setMapObj);
                } else {
                    previousSets.add(null);
                }
            }
            ex.put("previousSets", previousSets);
        } else {
            ex.put("previousLog", null);
            ex.put("previousSets", Collections.emptyList());
        }

        // Apply plate solver adjustment for free weights
        GymService.PlateSolverResult plateRes = gymService.resolveFreeWeight(name, targetWeight);
        if (plateRes.isAdjusted()) {
            ex.put("targetWeight", plateRes.getAdjustedWeight());
            ex.put("plateAdjusted", true);
            ex.put("rawTargetWeight", targetWeight);
        } else {
            ex.put("targetWeight", targetWeight);
            ex.put("plateAdjusted", false);
        }

        ex.put("targetReps", targetRepsVal);
    }

    private double getOneRmVal(OneRmSetting oneRms, String liftType) {
        if ("squat".equalsIgnoreCase(liftType)) return oneRms.getSquat();
        if ("bench".equalsIgnoreCase(liftType)) return oneRms.getBench();
        if ("deadlift".equalsIgnoreCase(liftType)) return oneRms.getDeadlift();
        if ("ohp".equalsIgnoreCase(liftType)) return oneRms.getOhp();
        return 100.0;
    }

    private String getTargetMuscle(String exName) {
        if (exName == null) return "기타";
        String name = exName.toLowerCase();
        if (name.contains("벤치프레스") || name.contains("bench press") || name.contains("플라이") || name.contains("fly") || name.contains("딥스") || name.contains("dips")) {
            return "가슴";
        }
        if (name.contains("로우") || name.contains("row") || name.contains("풀다운") || name.contains("pulldown") || name.contains("풀업") || name.contains("pull-up") || name.contains("pull up")) {
            return "등";
        }
        if (name.contains("스쿼트") || name.contains("squat") || name.contains("데드리프트") || name.contains("deadlift") || name.contains("레그프레스") || name.contains("leg press") || name.contains("레그 프레스") || name.contains("레그 익스텐션") || name.contains("익스텐션") || name.contains("레그 컬") || name.contains("레그컬") || name.contains("카프 레이즈") || name.contains("카프레이즈") || name.contains("calf raise") || name.contains("레이즈") && name.contains("레그") || name.contains("복근") || name.contains("레그 레이즈")) {
            return "하체";
        }
        if (name.contains("오버헤드 프레스") || name.contains("ohp") || name.contains("숄더 프레스") || name.contains("shoulder press") || name.contains("레터럴 레이즈") || name.contains("lateral raise") || name.contains("델트") || name.contains("페이스 풀") || name.contains("face pull")) {
            return "어깨";
        }
        if (name.contains("컬") || name.contains("curl") || name.contains("트라이셉스") || name.contains("triceps") || name.contains("푸쉬다운") || name.contains("푸쉬 다운") || name.contains("푸시다운") || name.contains("푸시 다운") || name.contains("pushdown") || name.contains("익스텐션") && name.contains("삼두")) {
            return "팔";
        }
        return "기타";
    }

    private Map<String, Object> createDay(String id, String name, List<Map<String, Object>> exercises) {
        Map<String, Object> day = new HashMap<>();
        day.put("id", id);
        day.put("name", name);
        day.put("exercises", exercises);
        return day;
    }

    private Map<String, Object> createExercise(String name, int sets, int targetReps, String repsRange,
                                               double rpeTarget, boolean coreLift, String coreLiftType,
                                               double intensity, double defaultWeight) {
        Map<String, Object> ex = new HashMap<>();
        ex.put("name", name);
        ex.put("sets", sets);
        ex.put("targetReps", targetReps);
        ex.put("repsRange", repsRange);
        ex.put("rpeTarget", rpeTarget);
        ex.put("coreLift", coreLift);
        ex.put("coreLiftType", coreLiftType);
        ex.put("intensity", intensity);
        ex.put("defaultWeight", defaultWeight);
        return ex;
    }
}
