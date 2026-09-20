(ns com.blockether.vis.lang.interface.packs-test
  "Pack discovery: the descriptor contract, initialization order and the Python
   surface files a pack ships for the sandbox."
  (:require [clojure.java.io :as io]
            [com.blockether.vis.core :as vis]
            [com.blockether.vis.lang.interface.core :as core]
            [com.blockether.vis.lang.interface.packs :as packs]
            [lazytest.core :refer [defdescribe expect it throws?]]))

(def ^:private events "What a fake pack did, in the order it happened." (atom []))

(defn record-register!
  "Stands in for a pack's `:register` entry point."
  []
  (swap! events conj [:register "fake"]))

(defn- descriptor-file
  [content]
  (let [file (java.io.File/createTempFile "pack" ".edn")]
    (.deleteOnExit file)
    (spit file content)
    (io/as-url file)))

(defn- read-descriptor [content] (#'packs/read-descriptor (descriptor-file content)))

(defdescribe
  pack-descriptor-test
  (it "reads a descriptor with the Python surfaces the pack ships"
      (expect (= {:pack "fake"
                  :register 'com.blockether.vis.lang.interface.packs-test/record-register!
                  :python ["language_surface_fake.py"]}
                 (read-descriptor
                   (str "{:pack \"fake\" "
                        ":register com.blockether.vis.lang.interface.packs-test/record-register! "
                        ":python [\"language_surface_fake.py\"]}")))))
  (it "keeps `:python` optional"
      (expect
        (nil? (:python
                (read-descriptor
                  (str
                    "{:pack \"fake\" "
                    ":register com.blockether.vis.lang.interface.packs-test/record-register!}"))))))
  (it "refuses a `:python` entry that is not a vector of file names"
      (expect (throws?
                clojure.lang.ExceptionInfo
                #(read-descriptor
                   (str "{:pack \"fake\" "
                        ":register com.blockether.vis.lang.interface.packs-test/record-register! "
                        ":python \"language_surface_fake.py\"}")))))
  (it "refuses a descriptor without a qualified initializer"
      (expect (throws? clojure.lang.ExceptionInfo
                       #(read-descriptor "{:pack \"fake\" :register register!}"))))
  (it "refuses a tagged literal"
      (expect (throws? clojure.lang.ExceptionInfo
                       #(read-descriptor
                          "{:pack \"fake\" :register a/b :python #java.io.File [\"x\"]}")))))

(defdescribe
  pack-initialization-test
  (it "registers a pack's Python surfaces BEFORE its own initializer runs"
      (reset! events [])
      (with-redefs [packs/descriptors
                    (fn []
                      [{:pack "fake"
                        :register 'com.blockether.vis.lang.interface.packs-test/record-register!
                        :python ["language_surface_fake.py"]}])

                    vis/register-bundled-extension-sources!
                    (fn [sources]
                      (swap! events conj [:python sources]))]

        (expect (= ["fake"] (packs/initialize!)))
        (expect (= [[:python ["language_surface_fake.py"]] [:register "fake"]] @events))))
  (it "registers nothing for a pack that ships no Python surface"
      (reset! events [])
      (with-redefs [packs/descriptors
                    (fn []
                      [{:pack "fake"
                        :register 'com.blockether.vis.lang.interface.packs-test/record-register!}])

                    vis/register-bundled-extension-sources!
                    (fn [sources]
                      (swap! events conj [:python sources]))]

        (expect (= ["fake"] (packs/initialize!)))
        (expect (= [[:register "fake"]] @events))))
  (it "stops startup when a pack cannot be resolved"
      (with-redefs [packs/descriptors
                    (fn []
                      [{:pack "fake" :register 'no.such.pack/register!}])

                    vis/register-bundled-extension-sources!
                    (fn [_]
                      nil)]

        (expect (throws? clojure.lang.ExceptionInfo #(packs/initialize!))))))

(defdescribe python-extension-sources-test
             (it "ships every Python source it declares"
                 (doseq [source core/python-extension-sources]
                   (expect (some? (io/resource (str "vis-extensions/" source))) source)))
             (it "declares the base surface and its shared package"
                 (expect (= "language_surface.py" (first core/python-extension-sources)))
                 (expect (every? #(re-matches #"[a-z_/]+\.py" %) core/python-extension-sources))))
