package com.mattvena.powerlifting.service;

import com.google.api.client.googleapis.javanet.GoogleNetHttpTransport;
import com.google.api.client.json.gson.GsonFactory;
import com.google.api.services.sheets.v4.Sheets;
import com.google.api.services.sheets.v4.SheetsScopes;
import com.google.api.services.sheets.v4.model.*;
import com.google.auth.http.HttpCredentialsAdapter;
import com.google.auth.oauth2.GoogleCredentials;
import com.mattvena.powerlifting.model.OneRmSetting;
import com.mattvena.powerlifting.model.WorkoutLog;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import jakarta.annotation.PostConstruct;
import java.io.*;
import java.security.GeneralSecurityException;
import java.util.*;

@Service
public class GoogleSheetsService {

    @Value("${google.sheets.spreadsheet-id}")
    private String spreadsheetId;

    @Value("${google.sheets.credentials-path}")
    private String credentialsPath;

    private Sheets sheetsService;
    private boolean isFallback = false;

    // In-memory DB fallback
    private OneRmSetting inMemoryOneRm = new OneRmSetting(150.0, 100.0, 160.0, 60.0);
    private final List<WorkoutLog> inMemoryLogs = new ArrayList<>();

    @PostConstruct
    public void init() {
        try {
            if ("YOUR_SPREADSHEET_ID_HERE".equals(spreadsheetId) || spreadsheetId == null || spreadsheetId.trim().isEmpty()) {
                throw new IllegalArgumentException("Spreadsheet ID is placeholder or empty.");
            }

            InputStream credentialStream = null;
            File keyFile = new File(credentialsPath);
            if (keyFile.exists()) {
                credentialStream = new FileInputStream(keyFile);
            } else {
                credentialStream = getClass().getClassLoader().getResourceAsStream(credentialsPath);
            }

            if (credentialStream == null) {
                throw new FileNotFoundException("Google credentials file '" + credentialsPath + "' not found. Put it in root or classpath.");
            }

            GoogleCredentials credentials = GoogleCredentials.fromStream(credentialStream)
                    .createScoped(Collections.singleton(SheetsScopes.SPREADSHEETS));

            sheetsService = new Sheets.Builder(
                    GoogleNetHttpTransport.newTrustedTransport(),
                    GsonFactory.getDefaultInstance(),
                    new HttpCredentialsAdapter(credentials))
                    .setApplicationName("Matt Vena Powerlifting WebApp")
                    .build();

            // Verify spreadsheet connectivity & tabs
            ensureTabsExist();
            
            System.out.println(">>> Google Sheets successfully connected and initialized! <<<");
        } catch (Exception e) {
            System.err.println(">>> Google Sheets API Connection Failed: " + e.getMessage() + ". USING IN-MEMORY FALLBACK DB. <<<");
            isFallback = true;
        }
    }

    private void ensureTabsExist() throws IOException {
        Spreadsheet spreadsheet = sheetsService.spreadsheets().get(spreadsheetId).execute();
        List<Sheet> sheets = spreadsheet.getSheets();
        
        boolean hasSettingTab = false;
        boolean hasLogTab = false;

        for (Sheet sheet : sheets) {
            String title = sheet.getProperties().getTitle();
            if ("Setting_1RM".equals(title)) {
                hasSettingTab = true;
            } else if ("Workout_Logs".equals(title)) {
                hasLogTab = true;
            }
        }

        List<Request> requests = new ArrayList<>();
        if (!hasSettingTab) {
            requests.add(new Request().setAddSheet(new AddSheetRequest().setProperties(new SheetProperties().setTitle("Setting_1RM"))));
        }
        if (!hasLogTab) {
            requests.add(new Request().setAddSheet(new AddSheetRequest().setProperties(new SheetProperties().setTitle("Workout_Logs"))));
        }

        if (!requests.isEmpty()) {
            BatchUpdateSpreadsheetRequest batchRequest = new BatchUpdateSpreadsheetRequest().setRequests(requests);
            sheetsService.spreadsheets().batchUpdate(spreadsheetId, batchRequest).execute();
        }

        // Initialize Setting_1RM headers and default values if empty
        try {
            ValueRange response = sheetsService.spreadsheets().values()
                    .get(spreadsheetId, "Setting_1RM!A1:J2")
                    .execute();
            List<List<Object>> values = response.getValues();
            if (values == null || values.isEmpty()) {
                List<List<Object>> initialData = Arrays.asList(
                        Arrays.asList("Squat", "Bench", "Deadlift", "OHP", "ActiveSplit", "FatigueDay1", "FatigueDay2", "FatigueDay3", "FatigueDay4", "FatigueDay5"),
                        Arrays.asList("150.0", "100.0", "160.0", "60.0", "5", "FALSE", "FALSE", "FALSE", "FALSE", "FALSE")
                );
                ValueRange body = new ValueRange().setValues(initialData);
                sheetsService.spreadsheets().values()
                        .update(spreadsheetId, "Setting_1RM!A1:J2", body)
                        .setValueInputOption("RAW")
                        .execute();
            } else {
                List<Object> header = values.get(0);
                if (header.size() < 10) {
                    List<List<Object>> upgradedData = new ArrayList<>();
                    List<Object> newHeader = Arrays.asList("Squat", "Bench", "Deadlift", "OHP", "ActiveSplit", "FatigueDay1", "FatigueDay2", "FatigueDay3", "FatigueDay4", "FatigueDay5");
                    
                    List<Object> newValues = new ArrayList<>();
                    List<Object> existingValues = (values.size() > 1) ? values.get(1) : Arrays.asList("150.0", "100.0", "160.0", "60.0");
                    for (int i = 0; i < 4; i++) {
                        if (existingValues.size() > i) newValues.add(existingValues.get(i).toString());
                        else newValues.add(i == 0 ? "150.0" : i == 1 ? "100.0" : i == 2 ? "160.0" : "60.0");
                    }
                    newValues.add("5"); // ActiveSplit default
                    for (int i = 0; i < 5; i++) {
                        newValues.add("FALSE"); // Fatigue defaults
                    }
                    upgradedData.add(newHeader);
                    upgradedData.add(newValues);
                    
                    ValueRange body = new ValueRange().setValues(upgradedData);
                    sheetsService.spreadsheets().values()
                            .update(spreadsheetId, "Setting_1RM!A1:J2", body)
                            .setValueInputOption("RAW")
                            .execute();
                }
            }
        } catch (Exception e) {
            System.err.println("Setting_1RM init check failed, will use fallback default values or write direct: " + e.getMessage());
        }

        // Initialize/Migrate Workout_Logs header
        try {
            boolean needMigration = true;
            if (!isFallback) {
                try {
                    ValueRange response = sheetsService.spreadsheets().values()
                            .get(spreadsheetId, "Workout_Logs!A1:L1")
                            .execute();
                    List<List<Object>> values = response.getValues();
                    if (values != null && !values.isEmpty()) {
                        List<Object> headers = values.get(0);
                        if (headers.size() >= 12 && "목표무게(kg)".equals(headers.get(10).toString())) {
                            needMigration = false;
                        }
                    }
                } catch (Exception e) {
                    needMigration = true;
                }

                if (needMigration) {
                    // Truncate and write new headers
                    sheetsService.spreadsheets().values()
                            .clear(spreadsheetId, "Workout_Logs!A:Z", new com.google.api.services.sheets.v4.model.ClearValuesRequest())
                            .execute();

                    List<List<Object>> initialHeader = Collections.singletonList(
                            Arrays.asList("날짜", "분할", "주차", "일차", "운동종목", "세트수", "무게(kg)", "횟수(reps)", "RPE", "상태(SUCCESS/FAIL)", "목표무게(kg)", "목표횟수(reps)")
                    );
                    ValueRange body = new ValueRange().setValues(initialHeader);
                    sheetsService.spreadsheets().values()
                            .update(spreadsheetId, "Workout_Logs!A1:L1", body)
                            .setValueInputOption("RAW")
                            .execute();
                }
            }
            if (needMigration) {
                inMemoryLogs.clear();
            }
        } catch (Exception e) {
            System.err.println("Workout_Logs migration/truncate failed: " + e.getMessage());
        }
    }

    public OneRmSetting getOneRm() {
        if (isFallback) {
            return inMemoryOneRm;
        }

        try {
            ValueRange response = sheetsService.spreadsheets().values()
                    .get(spreadsheetId, "Setting_1RM!A2:J2")
                    .execute();
            List<List<Object>> values = response.getValues();
            if (values != null && !values.isEmpty() && values.get(0).size() >= 4) {
                List<Object> row = values.get(0);
                double squat = Double.parseDouble(row.get(0).toString().trim());
                double bench = Double.parseDouble(row.get(1).toString().trim());
                double deadlift = Double.parseDouble(row.get(2).toString().trim());
                double ohp = Double.parseDouble(row.get(3).toString().trim());
                
                int activeSplit = 5;
                if (row.size() >= 5) {
                    try {
                        activeSplit = Integer.parseInt(row.get(4).toString().trim());
                    } catch (Exception ex) {
                        activeSplit = 5;
                    }
                }
                boolean fd1 = false, fd2 = false, fd3 = false, fd4 = false, fd5 = false;
                if (row.size() >= 10) {
                    fd1 = Boolean.parseBoolean(row.get(5).toString().trim()) || "TRUE".equalsIgnoreCase(row.get(5).toString().trim());
                    fd2 = Boolean.parseBoolean(row.get(6).toString().trim()) || "TRUE".equalsIgnoreCase(row.get(6).toString().trim());
                    fd3 = Boolean.parseBoolean(row.get(7).toString().trim()) || "TRUE".equalsIgnoreCase(row.get(7).toString().trim());
                    fd4 = Boolean.parseBoolean(row.get(8).toString().trim()) || "TRUE".equalsIgnoreCase(row.get(8).toString().trim());
                    fd5 = Boolean.parseBoolean(row.get(9).toString().trim()) || "TRUE".equalsIgnoreCase(row.get(9).toString().trim());
                }
                
                // Keep memory synchronized
                inMemoryOneRm = new OneRmSetting(squat, bench, deadlift, ohp, activeSplit, fd1, fd2, fd3, fd4, fd5);
                return inMemoryOneRm;
            }
        } catch (Exception e) {
            System.err.println("Error reading 1RM from Sheets. Using cached memory values: " + e.getMessage());
        }
        return inMemoryOneRm;
    }

    public void updateOneRm(OneRmSetting setting) {
        this.inMemoryOneRm = setting;
        if (isFallback) {
            return;
        }

        try {
            List<List<Object>> updateValues = Collections.singletonList(
                    Arrays.asList(
                            String.valueOf(setting.getSquat()),
                            String.valueOf(setting.getBench()),
                            String.valueOf(setting.getDeadlift()),
                            String.valueOf(setting.getOhp()),
                            String.valueOf(setting.getActiveSplit()),
                            String.valueOf(setting.isFatigueDay1()).toUpperCase(),
                            String.valueOf(setting.isFatigueDay2()).toUpperCase(),
                            String.valueOf(setting.isFatigueDay3()).toUpperCase(),
                            String.valueOf(setting.isFatigueDay4()).toUpperCase(),
                            String.valueOf(setting.isFatigueDay5()).toUpperCase()
                    )
            );
            ValueRange body = new ValueRange().setValues(updateValues);
            sheetsService.spreadsheets().values()
                    .update(spreadsheetId, "Setting_1RM!A2:J2", body)
                    .setValueInputOption("RAW")
                    .execute();
        } catch (Exception e) {
            System.err.println("Error updating 1RM to Sheets: " + e.getMessage());
        }
    }

    public void appendWorkoutLogs(List<WorkoutLog> logs) {
        if (logs == null || logs.isEmpty()) {
            return;
        }

        // Add to in-memory first
        inMemoryLogs.addAll(logs);

        if (isFallback) {
            return;
        }

        try {
            List<List<Object>> rowValues = new ArrayList<>();
            for (WorkoutLog log : logs) {
                rowValues.add(Arrays.asList(
                        log.getDate(),
                        String.valueOf(log.getSplit()),
                        String.valueOf(log.getWeek()),
                        log.getDay(),
                        log.getExercise(),
                        String.valueOf(log.getSetNo()),
                        String.valueOf(log.getWeight()),
                        String.valueOf(log.getReps()),
                        String.valueOf(log.getRpe()),
                        log.getStatus(),
                        String.valueOf(log.getTargetWeight()),
                        String.valueOf(log.getTargetReps())
                ));
            }

            ValueRange body = new ValueRange().setValues(rowValues);
            sheetsService.spreadsheets().values()
                    .append(spreadsheetId, "Workout_Logs!A:L", body)
                    .setValueInputOption("RAW")
                    .execute();
        } catch (Exception e) {
            System.err.println("Error appending workout logs to Sheets: " + e.getMessage());
        }
    }

    public List<WorkoutLog> getWorkoutLogs() {
        if (isFallback) {
            return inMemoryLogs;
        }

        List<WorkoutLog> logs = new ArrayList<>();
        try {
            ValueRange response = sheetsService.spreadsheets().values()
                    .get(spreadsheetId, "Workout_Logs!A2:L")
                    .execute();
            List<List<Object>> values = response.getValues();
            if (values != null) {
                for (List<Object> row : values) {
                    int startIndex = 0;
                    if (row.size() > 0 && (row.get(0) == null || row.get(0).toString().trim().isEmpty())) {
                        if (row.size() > 1 && row.get(1) != null && row.get(1).toString().contains("-")) {
                            startIndex = 1;
                        }
                    }
                    
                    if (row.size() - startIndex < 10) continue;
                    
                    try {
                        WorkoutLog log = new WorkoutLog();
                        log.setDate(row.get(startIndex + 0).toString().trim());
                        log.setSplit(Integer.parseInt(row.get(startIndex + 1).toString().trim()));
                        log.setWeek(Integer.parseInt(row.get(startIndex + 2).toString().trim()));
                        log.setDay(row.get(startIndex + 3).toString().trim());
                        log.setExercise(row.get(startIndex + 4).toString().trim());
                        log.setSetNo(Integer.parseInt(row.get(startIndex + 5).toString().trim()));
                        log.setWeight(Double.parseDouble(row.get(startIndex + 6).toString().trim()));
                        log.setReps(Integer.parseInt(row.get(startIndex + 7).toString().trim()));
                        log.setRpe(Double.parseDouble(row.get(startIndex + 8).toString().trim()));
                        log.setStatus(row.get(startIndex + 9).toString().trim());

                        double tW = log.getWeight();
                        if (row.size() - startIndex >= 11) {
                            try {
                                tW = Double.parseDouble(row.get(startIndex + 10).toString().trim());
                            } catch (Exception e) {}
                        }
                        log.setTargetWeight(tW);

                        int tR = log.getReps();
                        if (row.size() - startIndex >= 12) {
                            try {
                                tR = Integer.parseInt(row.get(startIndex + 11).toString().trim());
                            } catch (Exception e) {}
                        }
                        log.setTargetReps(tR);
                        logs.add(log);
                    } catch (Exception ex) {
                        System.err.println("Warning: Skipped invalid workout log row: " + row + ". Error: " + ex.getMessage());
                    }
                }
            }
        } catch (Exception e) {
            System.err.println("Error reading workout logs from Sheets: " + e.getMessage() + ". Returning cache.");
            return inMemoryLogs;
        }
        return logs;
    }

    public boolean isFallback() {
        return isFallback;
    }
}
