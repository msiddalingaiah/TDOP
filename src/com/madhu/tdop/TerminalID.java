
/*
 * Copyright 2015 Madhu Siddalingaiah
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package com.madhu.tdop;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * TerminalID represents a class of Terminals, e.g. numbers or strings.
 * This could have been achieved with an enum, but this implementation is simpler.
 * 
 * @author Madhu Siddalingaiah
 */
public class TerminalID {
    private Pattern pattern;
    private Matcher matcher;
    private String name;
    
    public TerminalID(String name, String regex) {
        this.name = name;
        this.pattern = Pattern.compile(regex);
    }

    public void init(String input) {
        matcher = pattern.matcher(input);
    }

    public String getName() {
        return name;
    }

    public Matcher getMatcher() {
        return matcher;
    }

    @Override
    public String toString () {
        return name;
    }
}
