
import re

class Pattern(object):
    def __init__(self, name, regex):
        self.name = name
        self.pattern = re.compile(regex)
        
    def match(self, input, index):
        return self.pattern.match(input, index)
    
class Terminal(object):
    def __init__(self, name, value):
        self.name = name
        self.value = value

    def __str__(self):
        if self.name.lower() == self.value:
            return self.name
        return '%s(%s)' % (self.name, self.value)
        
class Tree(object):
    def __init__(self, *values):
        self.value = None
        if len(values) > 0:
            self.value = values[0]
        if len(values) > 1:
            self.children = [x for x in values[1:]]
        else:
            self.children = []

    def add(self, value):
        if isinstance(value, Tree):
            self.children.append(value)
        else:
            self.children.append(Tree(value))
        return self
        
    def __len__(self):
        return len(self.children)

    def isLeaf(self):
        return len(self.children) == 0

    def toDot(self):
        self.label(1)
        return 'digraph ast {%s\n}' % self.doToDot('')

    def label(self, id):
        self.id = id
        id += 1
        for c in self.children:
            id = c.label(id)
        return id

    def doToDot(self, dot):
        dot = '%s\n%d [label="%s"];' % (dot, self.id, self.value.value)
        for c in self.children:
            dot = c.doToDot(dot)
            dot = '%s\n%d -> %d;' % (dot, self.id, c.id)
        return dot

    def __str__(self):
        if self.isLeaf():
            return self.value.__str__()
        result = '(%s)' % self.value
        for c in self.children:
            result = '%s %s' % (result, c)
        return '%s)' % result

class Scanner(object):
    def __init__(self, input, patterns):
        self.input = input
        self.index = 0
        self.patterns = patterns
        self.terminal = None
        self.lookAhead = self.next()

    def next(self):
        while self.index < len(self.input) and self.input[self.index].isspace():
            self.index += 1
        if self.index >= len(self.input):
            return None
        for p in self.patterns:
            match = p.match(self.input, self.index)
            if match:
                self.index = match.end()
                return Terminal(p.name, match.group())
        raise Exception('Unrecognized input: %s' % (self.input[self.index]))
        
    def matches(self, *types):
        if self.lookAhead == None:
            return False
        for t in types:
            if t == self.lookAhead.name:
                self.terminal = self.lookAhead
                self.lookAhead = self.next()
                return True
        return False

    def expect(self, *types):
        if self.matches(*types):
            return self.terminal
        raise Exception('Expected %s, found %s' % (','.join(types), self.lookAhead))

    def atEnd(self):
        return self.lookAhead == None

class Parser(object):
    def __init__(self, scanner):
        self.sc = scanner
        self.prec = [('&&','||'), ('==','!=','>','<','>=','<='), ('+','-'), ('*','/','%')]

    def parse(self):
        tree = self.parseStatement()
        if not self.sc.atEnd():
            raise Exception('Unexpected input: %s' % self.sc.terminal)
        return tree

    def parseStatement(self):
        if self.sc.matches('{'):
            tree = Tree(self.sc.terminal)
            while not self.sc.matches('}'):
                tree.add(self.parseStatement())
            return tree
        if self.sc.matches('WHILE'):
            return Tree(self.sc.terminal, self.parseExp(), self.parseStatement())
        if self.sc.matches('BREAK'):
            tree = Tree(self.sc.terminal)
            self.sc.expect(';')
            return tree
        if self.sc.matches('IF'):
            tree = Tree(self.sc.terminal, self.parseExp(), self.parseStatement())
            if self.sc.matches('ELSE'):
                tree.add(self.parseStatement())
            return tree
        if self.sc.matches('ID'):
            id = self.sc.terminal
            if self.sc.matches('='):
                tree = Tree(self.sc.terminal, Tree(id), self.parseExp())
                self.sc.expect(';')
                return tree
        self.sc.expect(';')

    def parseExp(self):
        return self.parseHead(0)

    def parseHead(self, index):
        result = self.parseTail(index)
        while self.sc.matches(*self.prec[index]):
            result = Tree(self.sc.terminal, result, self.parseTail(index))
        return result
        
    def parseTail(self, index):
        if index >= len(self.prec)-1:
            return self.parsePrim()
        return self.parseHead(index + 1)

    def parsePrim(self):
        if self.sc.matches('('):
            tree = self.parseExp()
            self.sc.expect(')')
            return tree
        if self.sc.matches('-'):
            return Tree(self.sc.terminal, self.parsePrim())
        return Tree(self.sc.expect('INT', 'ID'))
                    
if __name__ == '__main__':
    patterns = []
    patterns.append(Pattern('INT', r'[0-9]+'))
    patterns.append(Pattern('IF', r'if'))
    patterns.append(Pattern('ELSE', r'else'))
    patterns.append(Pattern('WHILE', r'while'))
    patterns.append(Pattern('BREAK', r'break'))
    patterns.append(Pattern('ID', r'[a-zA-Z][a-zA-Z0-9_]*'))
    patterns.append(Pattern(';', r'\;'))
    patterns.append(Pattern('{', r'\{'))
    patterns.append(Pattern('}', r'\}'))
    patterns.append(Pattern('[', r'\['))
    patterns.append(Pattern(']', r'\]'))
    patterns.append(Pattern('(', r'\('))
    patterns.append(Pattern(')', r'\)'))
    patterns.append(Pattern('+', r'\+'))
    patterns.append(Pattern('-', r'\-'))
    patterns.append(Pattern('*', r'\*'))
    patterns.append(Pattern('/', r'\/'))
    patterns.append(Pattern('<=', r'\<\='))
    patterns.append(Pattern('>=', r'\>\='))
    patterns.append(Pattern('==', r'\=\='))
    patterns.append(Pattern('!=', r'\!\='))
    patterns.append(Pattern('&&', r'\&\&'))
    patterns.append(Pattern('||', r'\|\|'))
    patterns.append(Pattern('=', r'\='))
    patterns.append(Pattern('<', r'\<'))
    patterns.append(Pattern('>', r'\>'))
    patterns.append(Pattern('%', r'\%'))

    input = '''
    {
        i = 0;
        while i<10 {
            a = 2*3;
            if i % 1 == 0 {
                a = a + 1;
            } else {
                a = a + 2;
            }
            i = i+1;
        }
    }
    '''
    
    p = Parser(Scanner(input, patterns))
    dot = p.parse().toDot()
    print(dot)
    