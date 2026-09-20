(ns com.blockether.vis.lang.interface.packs
  "How language packs are found.

   A pack is a jar on the classpath that ships one resource,
   `META-INF/vis-lang/pack.edn`:

     {:pack \"clojure\"
      :register com.blockether.vis.lang.clojure.core/register!
      :python [\"language_surface_clojure.py\"]}

   `:pack` is the pack's short name and orders initialization, so a build that
   adds or drops a pack never changes the order of the others. `:register` is the
   pack's zero-argument initializer, which calls `core/register-pack!`. `:python`
   is optional: the Python surface files the pack ships under
   `resources/vis-extensions/`, which the engine materializes for the sandbox.

   The engine is not involved: it initializes this library, and the packs that
   shipped beside it initialize from here. A pack that fails to initialize stops
   startup rather than leaving half a language surface."
  (:require [clojure.edn :as edn]
            [com.blockether.vis.core :as vis]))

(def pack-resource "META-INF/vis-lang/pack.edn")

(defn- read-descriptor
  [url]
  (let [value (try (edn/read-string {:readers {}
                                     :default (fn [tag v]
                                                (throw (ex-info "Tagged literal is not allowed"
                                                                {:tag tag :value v})))}
                                    (slurp url))
                   (catch Throwable t
                     (throw (ex-info (str "Invalid EDN in pack descriptor " url)
                                     {:type :language-surface/invalid-pack-descriptor
                                      :resource (str url)}
                                     t))))]
    (when-not (and (map? value)
                   (string? (:pack value))
                   (seq (:pack value))
                   (qualified-symbol? (:register value))
                   (or (nil? (:python value))
                       (and (vector? (:python value)) (every? string? (:python value)))))
      (throw (ex-info
               (str "Invalid pack descriptor " url)
               {:type :language-surface/invalid-pack-descriptor :resource (str url) :value value})))
    value))

(defn descriptors
  "Every pack descriptor on the classpath, ordered by `:pack`."
  []
  (->> (enumeration-seq (.getResources (clojure.lang.RT/baseLoader) pack-resource))
       (map read-descriptor)
       (sort-by :pack)
       vec))

(defn initialize!
  "Initialize every pack on the classpath, in `:pack` order, once each.
   Answers the pack names that registered."
  []
  (reduce (fn [acc {:keys [pack register python]}]
            (when (seq python) (vis/register-bundled-extension-sources! python))
            (let [f (try (requiring-resolve register)
                         (catch Throwable t
                           (throw (ex-info (str "Language pack " pack " failed to load")
                                           {:type :language-surface/pack-failed :pack pack}
                                           t))))]
              (when-not (ifn? f)
                (throw (ex-info (str "Language pack " pack " has no initializer " register)
                                {:type :language-surface/pack-failed :pack pack})))
              (try (f)
                   (catch Throwable t
                     (throw (ex-info (str "Language pack " pack " failed to register")
                                     {:type :language-surface/pack-failed :pack pack}
                                     t))))
              (conj acc pack)))
          []
          (descriptors)))
