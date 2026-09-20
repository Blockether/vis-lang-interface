(ns com.blockether.vis.lang.interface.presentation
  "Activity presentation for the language tools.

   Each tool this library binds owns its presentation here, the way every Vis
   binding owns one: a start headline, a settled headline, start visibility and
   the bounded evidence a finished call shows. The engine keeps no knowledge of
   these operations; it only renders what the binding declares.

   Evidence stays public and bounded. Only counts and outcome flags read the
   complete result; every displayed path and all body text comes from the
   bounded public value."
  (:require [clojure.string :as str]
            [com.blockether.vis.core :as vis :refer
             [activity-counted-label activity-field activity-label activity-preview
              activity-result-blocks activity-scalar activity-select-result activity-summary-line
              activity-visible-result] :rename
             {activity-counted-label counted-label
              activity-field field
              activity-label label
              activity-preview session-preview
              activity-result-blocks result-blocks
              activity-scalar scalar
              activity-select-result select-result
              activity-summary-line summary-line
              activity-visible-result visible-result}]))

(def ^:private tool-headlines
  "Each language tool owns its start headline, settled headline and start visibility."
  {"run_tests" ["Run tests" "Ran tests" true]
   "lint_code" ["Lint code" "Linted" true]
   "format_code" ["Format code" "Formatted" true]
   "repl_eval" ["Evaluate code" "Evaluated" true]
   "repl_start" ["Start REPL" "Started REPL" true]
   "repl_status" ["Check REPL status" "Checked REPL status" false]
   "repl_connect" ["Connect to REPL" "Connected to REPL" true]
   "repl_stop" ["Stop REPL" "Stopped REPL" true]})

(def ^:private result-fields
  "The result keys a settled REPL-lifecycle row shows, in this order."
  {"repl_start" ["message" "log_tail" "exit"]
   "repl_status" ["resources" "message" "log_tail" "exit"]
   "repl_connect" ["message"]
   "repl_stop" ["message"]})

(defn- repl-presentation
  [value]
  (let [language
        (or (field value "language") "text")

        code
        (field value "code")

        status
        (field value "status")

        statuses
        (if (coll? status) (set status) #{status})

        timeout?
        (or (true? (field value "timed_out")) (contains? statuses "timeout"))

        error-text
        (some #(let [v (field value %)] (when (vis/non-blank-string? v) v))
              ["exc" "error_message" "ex" "root_ex"])

        error?
        (or error-text (false? (field value "ok")) (contains? statuses "eval-error"))

        values
        (field value "values")

        result
        (if (seq values) (str/join "\n" values) (field value "value"))

        result
        (when-not (or (nil? result)
                      (= result
                         (case language
                           "clojure"
                           "nil"

                           "python"
                           "None"

                           nil)))
          (scalar result))

        section
        (fn [title text syntax]
          (when (vis/non-blank-string? text)
            [{"type" "heading" "text" title}
             (cond-> {"type" "code" "text" text}
               syntax
               (assoc "language" syntax))]))

        trace
        (field value "trace")

        error-body
        (str/join "\n"
                  (remove str/blank?
                    [(or error-text "Evaluation failed")
                     (when (seq trace) (if (string? trace) trace (str/join "\n" trace)))
                     (when-let [data (field value "error_data")]
                       (str "ex-data: " data))]))]

    {"headline" (cond timeout? "Evaluation timed out"
                      error? "Evaluation failed"
                      :else "Evaluated")
     "summary" (str (case language
                      "clojure"
                      "Clojure"

                      "python"
                      "Python"

                      language)
                    " REPL")
     "content" (vec (concat (section "Program" code language)
                            (section "Stdout" (field value "out") nil)
                            (section "Stderr" (field value "err") nil)
                            (cond timeout? (section "Timeout"
                                                    (str "Evaluation timed out"
                                                         (when-let [ms (field value "ms")]
                                                           (str " after " ms "ms"))
                                                         ".")
                                                    nil)
                                  error? (section "Error" error-body nil)
                                  :else (section "Result" result language))))}))

(defn- format-summary
  "Summarize complete format results using only counts and outcome flags, never source text."
  [value]
  (let [files
        (field value "files")

        changed
        (field value "changed")

        incomplete?
        (or (field value "unbalanced")
            (field value "error")
            (some #(or (field % "unbalanced") (field % "error")) files))]

    (cond incomplete? "Formatting incomplete"
          (and (sequential? files) (empty? files)) "No files to format"
          (and (sequential? files) (number? changed))
          (str changed " of " (counted-label (count files) "file") " changed")
          (true? changed) "Formatting changed"
          (false? changed) "No formatting changes"
          :else "No formatting result")))

(defn format-result
  "Compact formatting evidence before activity bounds; complete per-file data stays in the result."
  [value]
  (let [files
        (field value "files")

        diagnostics
        (filter #(or (field % "unbalanced") (field % "error")) files)]

    (cond-> (assoc (select-result ["path" "formatter" "formatters" "repaired" "repairs" "unbalanced"
                                   "error" "diagnostics"]
                                  value)
              "summary" (format-summary value))
      (seq diagnostics)
      (assoc "diagnostics" (vec diagnostics)))))

(defn- lint-summary
  "Summarize complete severity counts before per-finding evidence is bounded."
  [value]
  (let [errors
        (field value "error")

        warnings
        (field value "warning")

        info
        (field value "info")

        files
        (field value "files")]

    (if (every? number? [errors warnings info])
      (let [clean? (every? zero? [errors warnings info])]
        (if (and clean? (= 0 files))
          "No files to lint"
          (str (if clean?
                 "No lint findings"
                 (str (counted-label errors "error")
                      " · "
                      (counted-label warnings "warning")
                      " · "
                      info
                      " info"))
               (when (number? files) (str " · " (counted-label files "file") " checked")))))
      "No lint result")))

(defn- clean-lint-result?
  [value]
  (and (every? #(and (number? %) (zero? (double %)))
               (map #(field value %) ["error" "warning" "info"]))
       (empty? (field value "findings"))))

(defn- repl-status-summary
  [value]
  (let [result
        (field value "result")

        status
        (if (and result (not= "status" result)) result (field value "status"))

        host
        (field value "host")

        port
        (field value "port")

        resources
        (field value "resources")]

    (summary-line [(case status
                     "up"
                     "Running"

                     "down"
                     "Not running"

                     "already-running"
                     "Already running"

                     (if status (label status) "No REPL status")) (field value "cwd")
                   (when (or host port) (str (or host "127.0.0.1") (when port (str ":" port))))
                   (when-let [build (field value "build")]
                     (str "Build " build)) (when (true? (field value "external")) "External REPL")
                   (when (seq resources) (counted-label (count resources) "live REPL"))])))

(defn- test-target-summary
  "What a run_tests call SELECTED, on one line: the whole selection while it fits,
   else its first entry and how many others there were. A whole-suite run selected
   nothing worth naming — its counts already say so."
  [value]
  (let [target
        (str/trim (str (field value "target")))

        entries
        (remove str/blank? (str/split target #",\s*"))]

    (cond (or (str/blank? target) (= target "full suite")) nil
          (and (next entries) (> (count target) 60))
          (str (first entries) " +" (dec (count entries)) " more")
          :else (session-preview target 60))))

(defn- clean-test-result?
  "A run that passed, finished and reported no fault: its runner transcript only
   repeats the counts."
  [value]
  (and (true? (field value "is_pass"))
       (not (field value "timed_out"))
       (empty? (field value "failures"))))

(defn- test-body
  "What a finished run shows below its summary: never the counts the summary owns,
   never a flag for something that did not happen, and on a clean run not the
   runner's own transcript either."
  [value clean?]
  (if (map? value)
    (into {}
          (remove (comp false? val))
          (cond-> (dissoc value :total "total" :pass "pass" :fail "fail" :errored "errored")
            clean?
            (dissoc :output "output")))
    value))

(defn- test-summary
  [value]
  (let [total
        (field value "total")

        failed
        (field value "fail")

        errored
        (field value "errored")]

    (summary-line [(test-target-summary value)
                   (cond (field value "timed_out") "Test run timed out"
                         (field value "error") "Test run failed"
                         (and (number? total) (zero? (long total))) "No tests ran"
                         (number? total)
                         (summary-line
                           [(counted-label total "test")
                            (if (number? failed) (str failed " failed") "Failure count unavailable")
                            (when (and (number? errored) (pos? (long errored)))
                              (str errored " errored"))])
                         :else "No test result")])))

(defn result-presentation
  "Result view for one language tool. Unknown operations have no view."
  [{:keys [operation result]} value]
  (when (contains? tool-headlines (name operation))
    (let [op
          (name operation)

          headline
          (if (and (str/starts-with? op "repl_")
                   (or (= "failed" (field value "status"))
                       (contains? #{"failed" "no-launcher"} (field value "result"))))
            "REPL unavailable"
            (second (get tool-headlines op)))

          summary
          (cond (= op "format_code")
                (str (or (field value "summary") (format-summary (or result value)))
                     (when (true? (field value "repaired")) " · Syntax repaired")
                     (when-let [target (field value "path")]
                       (str " · " target)))
                (= op "lint_code") (lint-summary (or result value))
                (= op "run_tests") (test-summary (or result value))
                (contains? #{"repl_start" "repl_status" "repl_connect" "repl_stop"} op)
                (repl-status-summary value)
                :else (str (or (field value "summary") (field value "title") "")))

          content
          (cond (= op "format_code") (result-blocks (visible-result
                                                      (into {}
                                                            (remove (comp false? val))
                                                            (select-result ["repairs" "unbalanced"
                                                                            "error" "diagnostics"]
                                                                           (format-result value)))))
                :else
                (result-blocks
                  (visible-result
                    (let [public
                          (if (map? value) (dissoc value :title "title" :summary "summary") value)]
                      (cond
                        ;; Issue #260: a clean run's own transcript repeats the
                        ;; counts; a fault keeps it, below the structured rows.
                        (= op "run_tests") (test-body public (clean-test-result? (or result value)))
                        (get result-fields op) (select-result (get result-fields op) public)
                        :else public)))))]

      (cond (= op "repl_eval") (repl-presentation value)
            ;; Issue #270: a clean lint has nothing to open — provider, config and
            ;; target metadata only repeat the summary the row already carries.
            (and (= op "lint_code") (clean-lint-result? (or result value)))
            {"headline" headline "summary" summary "content" []}
            :else {"headline" headline "summary" summary "content" content}))))

(defn for-tool
  "Declare a language tool's presentation at its binding. Unknown operations are refused."
  [operation]
  (let [op (name operation)]
    (when-not (contains? tool-headlines op)
      (throw (ex-info "Missing language tool Activity presentation" {:operation operation})))
    {:headline (first (get tool-headlines op))
     :show-start (nth (get tool-headlines op) 2)
     :render (fn [details value]
               (result-presentation (assoc details :operation operation) value))}))
